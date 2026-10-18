import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Network,
  Database,
  LayoutDashboard,
  Server,
  Activity,
  Radar,
  Bell,
  Settings2,
  ShieldCheck,
  LogOut,
  Menu,
  Sun,
  Moon,
  ArrowUpRight,
  ChevronRight,
} from "lucide-react";
import { api, setCsrf, write } from "./api/client";
import { ErrorBox } from "./components/ui";
import { interceptLinks, useRoute } from "./router";
import "./styles/app.css";
import { Overview } from "./pages/Overview";
import { Devices } from "./pages/Devices";
import { Detail } from "./pages/Detail";
import { ActivityPage } from "./pages/ActivityPage";
import { Scans } from "./pages/Scans";
import { Notifications } from "./pages/Notifications";
import { Settings } from "./pages/Settings";
const client = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
      refetchInterval: 15000,
    },
  },
});
function App() {
  const [session, setSession] = useState<"loading" | "signedout" | "signedin">(
    "loading",
  );
  const [theme, setTheme] = useState(
    localStorage.getItem("dragon-theme") ||
      (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"),
  );
  const [mobile, setMobile] = useState(false);
  const route = useRoute();
  const [, setTick] = useState(0);
  React.useEffect(() => {
    // Re-render every 30s so relative times ("2m ago") stay current even
    // when polling returns unchanged data.
    const timer = setInterval(() => setTick((n) => n + 1), 30000);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMobile(false);
    document.addEventListener("click", interceptLinks);
    document.addEventListener("keydown", onKey);
    return () => {
      clearInterval(timer);
      document.removeEventListener("click", interceptLinks);
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  const firstRoute = React.useRef(true);
  React.useEffect(() => {
    setMobile(false);
    if (firstRoute.current) {
      firstRoute.current = false;
      return;
    }
    // Client-side navigation: start at the top and move focus to the new
    // page heading so screen readers announce it.
    scrollTo(0, 0);
    const focus = (tries: number) => {
      const heading = document.querySelector<HTMLElement>("#content h1");
      if (heading) heading.focus({ preventScroll: true });
      else if (tries) setTimeout(() => focus(tries - 1), 100);
    };
    requestAnimationFrame(() => focus(10));
  }, [route]);
  React.useEffect(() => {
    api("/session")
      .then((data) => {
        setCsrf(data.csrf);
        setSession("signedin");
      })
      .catch(() => setSession("signedout"));
  }, []);
  React.useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("dragon-theme", theme);
  }, [theme]);
  if (session === "loading")
    return <div className="startup">Connecting to Network Dragon…</div>;
  if (session === "signedout")
    return <Login onLogin={() => setSession("signedin")} />;
  const segments = route.split("?")[0].split("/");
  const path = segments[1] || "overview";
  const links = [
    ["overview", "Overview", LayoutDashboard],
    ["devices", "Devices", Server],
    ["activity", "Activity", Activity],
    ["scans", "Scans", Radar],
    ["notifications", "Notifications", Bell],
    ["settings", "Settings", Settings2],
  ] as const;
  const title = links.find((l) => l[0] === path)?.[1] || "Overview";
  document.title = `${title} · Network Dragon`;
  return (
    <div className="shell">
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <aside className={mobile ? "sidebar shown" : "sidebar"}>
        <a href="/" className="brand">
          <span className="brand-mark">
            <Network size={25} />
          </span>
          <span>
            network
            <span className="brand-second">
              dragon<span className="brand-dot">.</span>
            </span>
          </span>
        </a>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <div className="workspace">
          <span className="workspace-icon">
            <Database size={17} />
          </span>
          <span>
            Local installation<small>IPv4 / TCP monitor</small>
          </span>
        </div>
        <nav aria-label="Main navigation">
          {links.map(([key, text, Icon]) => (
            <a
              href={key === "overview" ? "/" : `/${key}`}
              key={key}
              className={path === key ? "active" : ""}
              aria-current={path === key ? "page" : undefined}
            >
              <Icon size={18} aria-hidden="true" />
              <span>{text}</span>
              {path === key && <span className="nav-dot" />}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="user">
            <span className="avatar">A</span>
            <span>
              Administrator<small>Local account</small>
            </span>
            <button
              className="icon-button"
              title="Sign out"
              aria-label="Sign out"
              onClick={async () => {
                await write("/session", "DELETE");
                client.clear();
                setSession("signedout");
              }}
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      {mobile && (
        <div
          className="scrim"
          aria-hidden="true"
          onClick={() => setMobile(false)}
        />
      )}
      <main>
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="mobile-menu icon-button"
              aria-label="Toggle navigation"
              aria-expanded={mobile}
              onClick={() => setMobile(!mobile)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>{title}</strong>
          </div>
          <div className="topbar-actions">
            <span className="local-label">
              <span /> Self-hosted
            </span>
            <button
              className="icon-button"
              aria-label="Toggle color theme"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? (
                <Sun size={18} aria-hidden="true" />
              ) : (
                <Moon size={18} aria-hidden="true" />
              )}
            </button>
          </div>
        </header>
        <div className="content" id="content" key={route} tabIndex={-1}>
          {path === "devices" ? (
            segments[2] ? (
              <Detail id={segments[2]} />
            ) : (
              <Devices />
            )
          ) : path === "activity" ? (
            <ActivityPage />
          ) : path === "scans" ? (
            <Scans />
          ) : path === "notifications" ? (
            <Notifications />
          ) : path === "settings" ? (
            <Settings />
          ) : (
            <Overview />
          )}
        </div>
        <footer>
          <span>
            NETWORK DRAGON <span className="version">v0.1.0</span>
          </span>
          <span>Observed states. Clear evidence. Less noise.</span>
        </footer>
      </main>
    </div>
  );
}

function Login({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState(""),
    [error, setError] = useState<Error | null>(null),
    [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <div className="login-card">
        <div className="brand-mark">
          <Network size={30} />
        </div>
        <div className="eyebrow">NETWORK DRAGON</div>
        <h1>
          A clearer view of
          <br />
          your network.
        </h1>
        <p>Sign in to your local monitoring workspace.</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              const data = await write("/session", "POST", { password });
              setCsrf(data.csrf);
              onLogin();
            } catch (e) {
              setError(e as Error);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Administrator password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <ErrorBox error={error} />
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
            <ArrowUpRight size={17} />
          </button>
        </form>
        <small>
          Set up the administrator with the local create-admin command.
        </small>
      </div>
      <div className="login-caption">
        <ShieldCheck size={16} /> Your inventory stays on your infrastructure.
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
