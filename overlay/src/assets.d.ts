// Vite turns an import ending in ?url into the URL of a file it copies into the build (src/mermaid.ts).
declare module "*?url" {
  const url: string;
  export default url;
}
