import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { PipelineProvider } from "./pipeline/PipelineContext";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <PipelineProvider>
      <React.StrictMode>
        <App />
      </React.StrictMode>
    </PipelineProvider>
  </BrowserRouter>
);
