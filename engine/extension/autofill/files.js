/**
 * files.js — File Input Assignment via DataTransfer & Fallback Downloader
 */

export async function attachPdfToFileInput(fileInputEl, pdfBlob, filename = 'Resume_Alireza_Nezami.pdf') {
  if (!fileInputEl || !pdfBlob) return false;

  try {
    const file = new File([pdfBlob], filename, { type: 'application/pdf' });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    fileInputEl.files = dataTransfer.files;

    fileInputEl.dispatchEvent(new Event('input', { bubbles: true }));
    fileInputEl.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  } catch (err) {
    console.warn('Programmatic file input assignment blocked:', err);
    return false;
  }
}

export function findResumeFileInput() {
  const fileInputs = Array.from(document.querySelectorAll('input[type="file"]'));
  for (const input of fileInputs) {
    const name = (input.name || input.id || input.getAttribute('aria-label') || '').toLowerCase();
    if (!name.includes('cover')) {
      return input;
    }
  }
  return fileInputs[0] || null;
}

export function findCoverLetterFileInput() {
  const fileInputs = Array.from(document.querySelectorAll('input[type="file"]'));
  for (const input of fileInputs) {
    const name = (input.name || input.id || input.getAttribute('aria-label') || '').toLowerCase();
    if (name.includes('cover')) {
      return input;
    }
  }
  return null;
}
