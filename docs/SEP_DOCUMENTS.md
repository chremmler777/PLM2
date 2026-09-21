# SEP topics as document slots

How the SEP checklist collects documents while the in-app forms are parked.
Written for the people who gather the existing filled forms for a project
(first 1994 and 2277) so the forms can be rebuilt in the UI afterwards.
Background: `memory/sep-forms-engine.md`, decision of 2026-09-21.

## The idea

Every SEP topic (a work item under a Q-gate) can hold files. Instead of
filling a form in the app, drop the document you already have on the topic:
the signed PDF, the Excel sheet, a photo of the paper. Once the documents
for a project are collected, the forms get rebuilt from them in the UI.

The forms engine and the **Open form** button are still there. They are
just not the way to work right now.

## Adding documents

On the project page, section **SEP Q-Gates**, tab **Checklist**:

1. Find the topic. Each row has a small drop area, "Drop files or click".
2. Drop one or more files on it, or click to pick them. Any file type,
   up to 100 MB per file, up to 20 files per drop.
3. The row shows `📎 n` for the number of files on the topic; the gate
   header shows the total for the gate.
4. Expand the row to see the list: file name (click to download), size,
   who uploaded it and when, and **remove**. Removing hides the file; it is
   not deleted from disk.

Every upload and removal writes a line into the topic's audit trail, next
to status and responsible changes.

Uploading is blocked on a closed gate, the same as editing the topic.

## Going through the documents

Tab **Documents** in the same section lists every file of the project by
gate and topic, with download links. Empty projects read "No documents
yet. Drop files on a topic to collect them." This is the view for the
later pass: open the documents topic by topic and rebuild each form.

## API

| Call | Purpose |
|---|---|
| `POST /api/v1/sep/items/{id}/files` | Upload one or more files (multipart field `files`); 413 over 100 MB per file or 20 files |
| `GET /api/v1/sep/items/{id}/files` | Files of a topic, newest first |
| `GET /api/v1/sep/items/{id}/files/{file_id}/download` | The file |
| `DELETE /api/v1/sep/items/{id}/files/{file_id}` | Hide a file (soft delete) |
| `GET /api/v1/sep/projects/{id}/files` | Every file of a project by gate and topic |

The SEP project payload (`GET /api/v1/sep/projects/{id}`) carries
`file_count` on every topic and gate. Files are stored under
`uploads/sep/<project>/<topic>/`. All routes are scoped to the caller's
organisation.

## Not covered

Hidden files are never purged from disk. Files are not tied to a form
instance; when a form is rebuilt, its source document stays on the topic as
a reference.
