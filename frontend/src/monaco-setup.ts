// Wire @monaco-editor/react to the locally-bundled `monaco-editor` package
// instead of its default jsDelivr CDN loader. This keeps the app offline_first
// (prompts/redesign/README.md security invariants): no external fetches beyond
// the LLM calls that the backend makes.
//
// Monaco's editor worker is imported through Vite's `?worker` suffix so it is
// bundled locally too. R is one of Monaco's built-in "basic-languages", so
// `language="r"` gives syntax highlighting without any extra download.
import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";

// monaco-editor already declares the global `MonacoEnvironment` type.
self.MonacoEnvironment = {
  getWorker() {
    return new editorWorker();
  },
};

loader.config({ monaco });
