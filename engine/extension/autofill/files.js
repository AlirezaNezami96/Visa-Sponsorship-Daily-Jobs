/**
 * files.js — PDF Blob Attachment via DataTransfer & File Input Setter
 */

export function base64ToBlob(base64, mimeType = 'application/pdf') {
  const byteChars = atob(base64);
  const byteNumbers = new Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) {
    byteNumbers[i] = byteChars.charCodeAt(i);
  }
  const byteArray = new Uint8Array(byteNumbers);
  return new Blob([byteArray], { type: mimeType });
}

export function attachBase64PdfToFileElement(fileInputEl, pdfBase64, filename = 'Resume_Alireza_Nezami.pdf') {
  if (!fileInputEl || !pdfBase64) return false;

  try {
    const blob = base64ToBlob(pdfBase64, 'application/pdf');
    const file = new File([blob], filename, { type: 'application/pdf' });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    fileInputEl.files = dataTransfer.files;

    fileInputEl.dispatchEvent(new Event('input', { bubbles: true }));
    fileInputEl.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  } catch (err) {
    console.warn('DataTransfer file input assignment failed:', err);
    return false;
  }
}
