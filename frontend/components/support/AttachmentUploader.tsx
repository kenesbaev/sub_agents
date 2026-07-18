"use client";

import { Paperclip, UploadCloud, X } from "lucide-react";
import { useRef, useState } from "react";

const MAX_BYTES = 10 * 1024 * 1024;
const ACCEPT = ".jpg,.jpeg,.png,.pdf,.doc,.docx,.txt";
const ALLOWED_EXTENSIONS = new Set(ACCEPT.split(","));

export function AttachmentUploader({ files, onChange }: { files: File[]; onChange: (files: File[]) => void }) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState("");

  function addFiles(list: FileList | null) {
    if (!list) return;
    const next = [...files];
    const rejected: string[] = [];
    for (const file of Array.from(list)) {
      const extension = file.name.includes(".") ? `.${file.name.split(".").pop()?.toLowerCase()}` : "";
      if (!ALLOWED_EXTENSIONS.has(extension) || file.size > MAX_BYTES) {
        rejected.push(file.name);
        continue;
      }
      if (!next.some((item) => item.name === file.name && item.size === file.size)) next.push(file);
    }
    onChange(next);
    setError(rejected.length ? `Not added: ${rejected.join(", ")}. Use JPG, PNG, PDF, DOC, DOCX, or TXT files up to 10MB.` : "");
  }

  return (
    <div className="attachment-control">
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(event) => {
          addFiles(event.target.files);
          event.currentTarget.value = "";
        }}
      />
      <button
        className="attachment-dropzone"
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          addFiles(event.dataTransfer.files);
        }}
      >
        <UploadCloud size={21} />
        <span>Drag & drop files here, or <b>click to browse</b></span>
        <small>Max file size 10MB. JPG, PNG, PDF, DOC, DOCX, TXT</small>
      </button>
      {error ? <p className="attachment-error" role="alert">{error}</p> : null}
      {files.length ? (
        <ul className="attachment-list">
          {files.map((file, index) => (
            <li key={`${file.name}-${file.size}`}>
              <Paperclip size={14} />
              <span>{file.name}</span>
              <button type="button" aria-label={`Remove ${file.name}`} onClick={() => onChange(files.filter((_, itemIndex) => itemIndex !== index))}>
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
