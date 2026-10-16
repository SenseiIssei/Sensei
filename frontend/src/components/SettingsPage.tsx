import { useEffect, useState } from "react";
import { ArrowUpCircle, Check, Monitor, Moon, Sun } from "lucide-react";
import { api } from "@/lib/api";
import { getThemeChoice, setThemeChoice, type ThemeChoice } from "@/lib/theme";
import type { SetupStatus, UpdateStatus } from "@/types";
import { Badge, Button, Card, CodeLine, Notice, PageHeader, Segmented } from "@/components/ui";
import { SetupWizard } from "@/components/SetupWizard";
import { Page } from "@/components/AppShell";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line-subtle py-3 first:border-t-0 first:pt-0 last:pb-0">
      <span className="text-[13px] text-fg-secondary">{label}</span>
      <div className="text-[13px] text-fg">{children}</div>
    </div>
  );
}

export function SettingsPage() {
  const [theme, setTheme] = useState<ThemeChoice>(getThemeChoice);
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [changingProvider, setChangingProvider] = useState(false);
  const [update, setUpdate] = useState<UpdateStatus | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    api.getSetupStatus().then(setSetup).catch(() => setSetup(null));
    // Without `force` this asks GitHub nothing unless SENSEI_UPDATE_CHECK is on;
    // it only tells us the running version.
    api.getUpdateStatus().then(setUpdate).catch(() => undefined);
  }, []);

  const checkNow = async () => {
    setChecking(true);
    try {
      setUpdate(await api.getUpdateStatus(true));
    } catch {
      setUpdate((u) => (u ? { ...u, error: "Could not reach the server." } : u));
    } finally {
      setChecking(false);
    }
  };

  return (
    <Page>
      <PageHeader title="Settings" description="Everything else is an environment variable — see the configuration reference." />

      <div className="space-y-4">
        <Card title="Appearance">
          <Row label="Theme">
            <div className="w-56">
              <Segmented<ThemeChoice>
                label="Theme"
                value={theme}
                onChange={(next) => {
                  setTheme(next);
                  setThemeChoice(next);
                }}
                options={[
                  { value: "system", label: "System", icon: <Monitor className="h-3.5 w-3.5" /> },
                  { value: "light", label: "Light", icon: <Sun className="h-3.5 w-3.5" /> },
                  { value: "dark", label: "Dark", icon: <Moon className="h-3.5 w-3.5" /> },
                ]}
              />
            </div>
          </Row>
        </Card>

        <Card
          title="Model for Sensei's own chat"
          description="The gateway does not need this: connected tools bring their own credentials."
          actions={
            setup &&
            !changingProvider && (
              <Button size="sm" onClick={() => setChangingProvider(true)}>
                Change
              </Button>
            )
          }
        >
          {!setup ? (
            <p className="text-[13px] text-muted">Asking the server…</p>
          ) : changingProvider ? (
            <SetupWizard
              embedded
              status={setup}
              onDone={() => {
                setChangingProvider(false);
                api.getSetupStatus().then(setSetup).catch(() => undefined);
              }}
            />
          ) : (
            <>
              <Row label="Provider">
                {setup.needs_setup ? <Badge tone="warning">none yet</Badge> : setup.active_provider}
              </Row>
              <Row label="Local models (Ollama)">
                {setup.ollama.running ? (
                  <Badge tone="success">{setup.ollama.models.length} installed</Badge>
                ) : (
                  <Badge>not running</Badge>
                )}
              </Row>
              <Row label="Compression">
                {setup.compression_enabled ? <Badge tone="success">on</Badge> : <Badge tone="warning">off</Badge>}
              </Row>
            </>
          )}
        </Card>

        <Card title="Updates" description="Sensei asks GitHub only when you press the button, unless SENSEI_UPDATE_CHECK is on.">
          <Row label="Installed version">
            <span className="num font-mono">{update?.current ?? "—"}</span>
          </Row>
          <Row label="Latest release">
            {update?.latest ? (
              update.update_available ? (
                <Badge tone="accent">
                  <ArrowUpCircle className="h-3 w-3" /> {update.latest} available
                </Badge>
              ) : (
                <Badge tone="success">
                  <Check className="h-3 w-3" /> up to date
                </Badge>
              )
            ) : (
              <Button size="sm" onClick={() => void checkNow()} disabled={checking}>
                {checking ? "Checking…" : "Check now"}
              </Button>
            )}
          </Row>
          {update?.error && (
            <div className="mt-3">
              <Notice tone="danger">{update.error}</Notice>
            </div>
          )}
          {update?.update_available && (
            <div className="mt-3 space-y-2">
              <CodeLine>sensei update</CodeLine>
              {update.url && (
                <a href={update.url} target="_blank" rel="noreferrer noopener" className="text-xs font-medium text-accent hover:text-accent-hover">
                  Release notes
                </a>
              )}
            </div>
          )}
        </Card>

        <Card title="Start with your computer">
          <p className="mb-3 text-[13px] text-muted">
            Uses the per-user login item of your system — a Run key on Windows, a LaunchAgent on
            macOS, a systemd user service on Linux. No administrator rights; reversible.
          </p>
          <CodeLine>sensei autostart on</CodeLine>
        </Card>

        <Card title="Privacy">
          <ul className="space-y-2 text-[13px] leading-5 text-fg-secondary">
            <li>No telemetry, in any build, behind any flag.</li>
            <li>The savings history is a local SQLite file of counters and model names — no prompts.</li>
            <li>API keys are encrypted on disk and sent only to the provider they belong to.</li>
            <li>This page loads no fonts, scripts or images from anyone else.</li>
          </ul>
        </Card>
      </div>
    </Page>
  );
}
