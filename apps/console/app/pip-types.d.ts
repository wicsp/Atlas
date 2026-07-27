// Type declarations for Document Picture-in-Picture API (Chrome 116+).
// https://developer.chrome.com/docs/web-platform/document-picture-in-picture

interface DocumentPictureInPictureOptions {
  width?: number;
  height?: number;
}

interface DocumentPictureInPicture {
  requestWindow(options?: DocumentPictureInPictureOptions): Promise<Window>;
}

interface Window {
  documentPictureInPicture: DocumentPictureInPicture;
}
