import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import "./index.css";
import { EnvironmentStoreProvider } from "@/store/EnvironmentStore";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 1000,
    },
  },
});

if (new URLSearchParams(window.location.search).get("desktop") === "1") {
  document.documentElement.classList.add("aris-desktop");
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <EnvironmentStoreProvider>
        <App />
      </EnvironmentStoreProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
