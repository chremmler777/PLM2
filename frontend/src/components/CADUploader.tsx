/**
 * CADUploader - Upload files (CAD, drawings, pictures, documents) for a part revision.
 * Falls back to legacy part-level upload when no revisionId is provided.
 */
import { useState, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

interface CADUploaderProps {
  partId: number;
  revisionId?: number | null;
  compact?: boolean;
  onUploadSuccess?: (fileId: number) => void;
}

const CAD_EXTENSIONS = ['.step', '.stp', '.iges', '.igs', '.stl', '.jt', '.catpart', '.catproduct'];
const DOC_EXTENSIONS = ['.pdf', '.dxf', '.dwg', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.docx', '.xlsx', '.pptx', '.txt', '.md', '.csv'];

export default function CADUploader({ partId, revisionId, compact = false, onUploadSuccess }: CADUploaderProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const queryClient = useQueryClient();

  const validExtensions = revisionId ? [...CAD_EXTENSIONS, ...DOC_EXTENSIONS] : ['.step', '.stp', '.catpart', '.catproduct'];

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      const url = revisionId
        ? `/v1/parts/${partId}/revisions/${revisionId}/files`
        : `/v1/parts/${partId}/files`;
      const res = await client.post(url, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return res.data;
    },
    onSuccess: (data: any) => {
      toast.success('File uploaded successfully');
      queryClient.invalidateQueries({ queryKey: ['part', partId] });
      queryClient.invalidateQueries({ queryKey: ['part-files', partId] });
      if (revisionId) {
        queryClient.invalidateQueries({ queryKey: ['revision-files', revisionId] });
      }
      onUploadSuccess?.(data.file_id ?? data.id);
    },
    onError: (error: any) => {
      const msg = error.response?.data?.detail || 'Upload failed';
      toast.error(msg);
    },
  });

  const handleFile = (file: File) => {
    const hasValidExt = validExtensions.some((ext) => file.name.toLowerCase().endsWith(ext));
    if (!hasValidExt) {
      toast.error(`Unsupported file type. Supported: ${validExtensions.join(', ')}`);
      return;
    }

    if (file.size > 100 * 1024 * 1024) {
      toast.error('File size must be under 100MB');
      return;
    }

    uploadMutation.mutate(file);
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    const files = e.dataTransfer.files;
    if (files && files[0]) {
      handleFile(files[0]);
    }
  };

  return (
    <div
      className={`border-2 border-dashed rounded-lg text-center transition-colors ${compact ? 'p-2' : 'p-8'} ${
        dragActive
          ? 'border-blue-500 bg-blue-50/10'
          : 'border-slate-600 hover:border-slate-500 bg-slate-800/50'
      } ${uploadMutation.isPending ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
      onDragEnter={handleDrag}
      onDragLeave={handleDrag}
      onDragOver={handleDrag}
      onDrop={handleDrop}
      onClick={() => !uploadMutation.isPending && fileInputRef.current?.click()}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept={validExtensions.join(',')}
        onChange={(e) => {
          if (e.target.files?.[0]) {
            handleFile(e.target.files[0]);
          }
        }}
        disabled={uploadMutation.isPending}
        className="hidden"
      />

      <div className="text-slate-300">
        {uploadMutation.isPending ? (
          <>
            <div className={`inline-block animate-spin rounded-full border-b-2 border-blue-500 ${compact ? 'h-4 w-4' : 'h-8 w-8 mb-2'}`}></div>
            <p className="text-sm">Uploading...</p>
          </>
        ) : compact ? (
          <p className="text-xs text-slate-400">+ Drop a file here or click to upload (CAD, drawing, picture, document)</p>
        ) : (
          <>
            <p className="text-lg font-medium mb-1">📁 Upload Files</p>
            <p className="text-sm text-slate-400">Drag & drop or click to select</p>
            <p className="text-xs text-slate-500 mt-2">
              {revisionId
                ? 'CAD (STEP, IGES, STL, CATIA), drawings (PDF, DXF), pictures & documents'
                : 'Supports: STEP (.step, .stp), CATIA (.catpart, .catproduct)'}
            </p>
            <p className="text-xs text-slate-500">Max file size: 100MB</p>
          </>
        )}
      </div>
    </div>
  );
}
