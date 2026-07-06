/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CIE_API_BASE?: string;
  readonly VITE_CIE_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
