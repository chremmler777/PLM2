/**
 * CADUploader - Upload STEP/CATIA 3D files for parts
 */
import { useState, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

interface CADUploaderProps {
  partId: number;
  onUploadSuccess?: () => void;
}

export default function CADUploader({ partId, onUploadSuccess }: CADUploaderProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const queryClient = useQueryClient();

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      const res = await client.post(`/v1/parts/${partId}/files`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return res.data;
    },
    onSuccess: () => {
      toast.success('3D file uploaded successfully');
      queryClient.invalidateQueries({ queryKey: ['part', partId] });
      onUploadSuccess?.();
    },
    onError: (error: any) => {
      const msg = error.response?.data?.detail || 'Upload failed';
      toast.error(msg);
    },
  });

  const handleFile = (file: File) => {
    const validTypes = [
      'application/step',
      'application/x-step',
      'application/stp',
      'application/x-stp',
      'application/octet-stream', // CATIA files
      'application/vnd.dassault-systemes.catpart',
      'application/vnd.dassault-systemes.catproduct',
    ];

    const validExtensions = ['.step', '.stp', '.catpart', '.catproduct'];
    const hasValidExt = validExtensions.some((ext) => file.name.toLowerCase().endsWith(ext));

    if (!validTypes.includes(file.type) && !hasValidExt) {
      toast.error('Only STEP (.step, .stp) and CATIA (.catpart, .catproduct) files are supported');
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
      className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
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
        accept=".step,.stp,.catpart,.catproduct"
        onChange={(e) => {
          if (e.target.files?.[0]) {
            handleFile(e.target.files[0]);
          }
        }}
        disabled={uploadMutation.isPending}
        className="hidden"
      />

      <div className="text-slate-300 mb-2">
        {uploadMutation.isPending ? (
          <>
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mb-2"></div>
            <p className="text-sm">Uploading...</p>
          </>
        ) : (
          <>
            <p className="text-lg font-medium mb-1">📁 Upload 3D Model</p>
            <p className="text-sm text-slate-400">Drag & drop or click to select</p>
            <p className="text-xs text-slate-500 mt-2">Supports: STEP (.step, .stp), CATIA (.catpart, .catproduct)</p>
            <p className="text-xs text-slate-500">Max file size: 100MB</p>
          </>
        )}
      </div>
    </div>
  );
}
