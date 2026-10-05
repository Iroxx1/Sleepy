import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "../../src/styles.css";
import "./mobile.css";
import { ThemeProvider } from "../../src/hooks/useTheme";
import { MobileAuthProvider } from "./auth";
import App from "./App";

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: true } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <MobileAuthProvider>
          <HashRouter>
            <App />
          </HashRouter>
        </MobileAuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
