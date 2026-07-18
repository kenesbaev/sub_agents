"use client";

import { Send } from "lucide-react";
import { FormEvent, useState } from "react";

import { AttachmentUploader } from "./AttachmentUploader";

export function SupportForm({ userEmail = "" }: { userEmail?: string }) {
  const [category, setCategory] = useState("");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [status, setStatus] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!category || !subject.trim() || !message.trim()) {
      setStatus("Complete the category, subject, and message fields.");
      return;
    }
    const attachmentNote = files.length
      ? `\n\nSelected attachments (attach them in your email client):\n${files.map((file) => `- ${file.name}`).join("\n")}`
      : "";
    const body = [`Category: ${category}`, userEmail ? `Account: ${userEmail}` : "", "", message.trim(), attachmentNote]
      .filter((line) => line !== "")
      .join("\n");
    window.location.href = `mailto:support@teamorai.uz?subject=${encodeURIComponent(subject.trim())}&body=${encodeURIComponent(body)}`;
    setStatus(files.length ? "Your email app opened. Attach the selected files before sending." : "Your email app opened with the support request.");
  }

  return (
    <form className="support-form-card" onSubmit={submit}>
      <div className="support-form-grid">
        <label>
          <span>Category</span>
          <select value={category} onChange={(event) => setCategory(event.target.value)} required>
            <option value="">Select a category</option>
            <option value="Account and access">Account and access</option>
            <option value="Connected Apps">Connected Apps</option>
            <option value="Billing">Billing</option>
            <option value="AI team or Office">AI team or Office</option>
            <option value="Bug report">Bug report</option>
          </select>
        </label>
        <label>
          <span>Subject</span>
          <input value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="Briefly describe your issue" required />
        </label>
      </div>
      <label>
        <span>Message</span>
        <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Please provide as much detail as possible so we can help you better..." required />
      </label>
      <div>
        <span className="support-field-label">Attachments (optional)</span>
        <AttachmentUploader files={files} onChange={setFiles} />
        <p className="support-email-note">This form opens your email app. Selected files stay on your device and must be attached there before sending.</p>
      </div>
      <div className="support-submit-row">
        {status ? <p role="status">{status}</p> : <span />}
        <button className="primary-button" type="submit"><Send size={16} /> Send Message</button>
      </div>
    </form>
  );
}
