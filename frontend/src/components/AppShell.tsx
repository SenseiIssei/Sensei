import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Gauge,
  Menu,
  MessageSquare,
  Monitor,
  Moon,
  Plug,
  Settings,
  Sun,
  Users,
  X,
} from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import { getThemeChoice, setThemeChoice, watchSystemTheme, type ThemeChoice } from "@/lib/theme";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { Logo, Segmented } from "@/components/ui";
import { formatTokens } from "@/lib/format";

const NAV = [
  { to: "/", label: "Overview", icon: Gauge, end: true },
  { to: "/workspace", label: "Chat", icon: MessageSquare },
  { to: "/connections", label: "Connections", icon: Plug },
  { to: "/settings", label: "Settings", icon: Settings },
];

function ThemeSwitch() {
  const [choice, setChoice] = useState<ThemeChoice>(getThemeChoice);
  useEffect(() => watchSystemTheme(), []);
  return (
    <Segmented<ThemeChoice>
      label="Theme"
      value={choice}
      onChange={(next) => {
        setChoice(next);
        setThemeChoice(next);
      }}
      options={[
        { value: "system", label: "System", icon: <Monitor className="h-3.5 w-3.5" /> },
        { value: "light", label: "Light", icon: <Sun className="h-3.5 w-3.5" /> },
        { value: "dark", label: "Dark", icon: <Moon className="h-3.5 w-3.5" /> },
      ]}
    />
  );
}

function SavedCounter() {
  const [saved, setSaved] = useState<number | null>(null);
  useEffect(() => {
    const read = () =>
      api
        .getSavings()
        .then((s) => setSaved(s.lifetime.tokens_saved))
        .catch(() => undefined);
    read();
    const timer = setInterval(read, 20_000);
    return () => clearInterval(timer);
  }, []);
  return (
    <NavLink
      to="/"
      className="block rounded-md border border-line bg-surface px-3 py-2.5 transition-colors hover:bg-raised"
    >
      <p className="eyebrow text-faint">Tokens saved</p>
      <p className="num mt-0.5 text-lg font-bold leading-6 text-gold-text">
        {saved === null ? "—" : formatTokens(saved)}
      </p>
    </NavLink>
  );
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="space-y-0.5">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            clsx(
              "relative flex h-9 items-center gap-3 rounded-sm px-2.5 text-sm transition-colors duration-150",
              isActive
                ? "bg-raised font-semibold text-fg before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-full before:bg-accent"
                : "font-medium text-muted hover:bg-hover hover:text-fg",
            )
          }
        >
          {({ isActive }) => (
            <>
              <Icon
                className={clsx("h-[17px] w-[17px]", isActive ? "text-accent" : "text-faint")}
                strokeWidth={1.75}
              />
              {label}
            </>
          )}
        </NavLink>
      ))}
      <p className="eyebrow px-2.5 pb-1 pt-5 text-faint">Team</p>
      <NavLink
        to="/chat"
        onClick={onNavigate}
        className="flex h-9 items-center gap-3 rounded-sm px-2.5 text-sm font-medium text-muted transition-colors hover:bg-hover hover:text-fg"
      >
        <Users className="h-[17px] w-[17px] text-faint" strokeWidth={1.75} />
        Shared chat
      </NavLink>
    </nav>
  );
}

function Brand() {
  return (
    <NavLink to="/" className="flex items-center gap-2.5">
      <Logo className="h-7 w-7" />
      <span className="text-[15px] font-semibold tracking-[-0.01em] text-fg">Sensei</span>
    </NavLink>
  );
}

export function AppShell() {
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();
  useEffect(() => setDrawer(false), [location.pathname]);

  const sidebar = (
    <div className="flex h-full flex-col gap-4 p-3">
      <div className="flex h-10 items-center px-1.5">
        <Brand />
      </div>
      <NavItems onNavigate={() => setDrawer(false)} />
      <div className="mt-auto space-y-3">
        <SavedCounter />
        <ThemeSwitch />
      </div>
    </div>
  );

  return (
    <div className="relative flex h-dvh w-full overflow-hidden bg-canvas">
      <ConnectionBanner />

      <aside className="hidden w-60 shrink-0 border-r border-line bg-canvas-deep lg:block">
        {sidebar}
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            aria-label="Close menu"
            onClick={() => setDrawer(false)}
            className="absolute inset-0 bg-[var(--scrim)]"
          />
          <aside className="animate-fade-in absolute inset-y-0 left-0 w-72 border-r border-line bg-canvas-deep shadow-pop">
            <button
              aria-label="Close menu"
              onClick={() => setDrawer(false)}
              className="absolute right-3 top-4 rounded-sm p-1.5 text-muted hover:bg-hover hover:text-fg"
            >
              <X className="h-4 w-4" />
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-canvas-deep px-4 shadow-bar lg:hidden">
          <button
            aria-label="Open menu"
            onClick={() => setDrawer(true)}
            className="rounded-sm p-1.5 text-muted hover:bg-hover hover:text-fg"
          >
            <Menu className="h-5 w-5" />
          </button>
          <Brand />
        </header>
        <main className="min-h-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

/** Scrollable page body with the standard gutter and max width. */
export function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className={clsx("mx-auto w-full px-4 py-6 sm:px-8 sm:py-8", wide ? "max-w-6xl" : "max-w-4xl")}>
        {children}
      </div>
    </div>
  );
}
