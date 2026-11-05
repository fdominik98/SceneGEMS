import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App.tsx";
import { installOverlayScrollbars } from "./app/overlayScrollbars";
import { installTheme } from "./app/theme";

const queryClient = new QueryClient();

installTheme();
installOverlayScrollbars();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
