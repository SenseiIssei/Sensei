import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SetupWizard } from "./SetupWizard";
import { api } from "@/lib/api";
import type { SetupStatus } from "@/types";

/**
 * The wizard is the first thing a new user sees, and the only screen standing
 * between them and a working install. These cover the paths that actually
 * decide whether they get there.
 */

const BASE: SetupStatus = {
  ready: false,
  needs_setup: true,
  configured_providers: [],
  active_provider: "openrouter",
  model_provider: "auto",
  ollama: { running: false, host: "http://localhost:11434", models: [], active_model: "glm-5.2" },
  hardware: {
    os: "Linux 6.8",
    arch: "x86_64",
    cpu_count: 16,
    ram_mb: 32000,
    usable_vram_mb: 16000,
    unified_memory: false,
    gpus: [{ name: "NVIDIA RTX 4080", vram_mb: 16000, vendor: "nvidia" }],
  },
  recommended_local_model: {
    id: "qwen2.5-coder:7b",
    name: "Qwen2.5 Coder 7B",
    params: "7B",
    size_mb: 4700,
    good_for: "Code completion and review.",
    fit: "comfortable",
  },
  catalog: [
    { id: "ollama", name: "Ollama (local)", free: true, models: [] },
    { id: "openrouter", name: "OpenRouter", free: true, models: ["zhipuai/glm-5.2"] },
    { id: "openai", name: "OpenAI", free: false, models: ["gpt-4o"] },
  ],
  compression_enabled: true,
};

const withOllama = (models: string[]): SetupStatus => ({
  ...BASE,
  ollama: { ...BASE.ollama, running: true, models },
});

beforeEach(() => {
  vi.spyOn(api, "getProviderModels").mockResolvedValue({
    provider: "openrouter",
    models: ["zhipuai/glm-5.2", "openai/gpt-4o"],
    source: "live",
    detail: "",
  });
  vi.spyOn(api, "applySettings").mockResolvedValue({});
});

describe("choosing a path", () => {
  it("leads with the local option when Ollama is already running", () => {
    render(<SetupWizard status={withOllama(["llama3.2:3b"])} onDone={vi.fn()} />);
    expect(screen.getByLabelText("Installed models")).toBeInTheDocument();
  });

  it("leads with the hosted option when nothing is running locally", () => {
    render(<SetupWizard status={BASE} onDone={vi.fn()} />);
    expect(screen.getByLabelText("Provider")).toBeInTheDocument();
  });
});

describe("the local path", () => {
  it("tells you how to install Ollama instead of failing silently", async () => {
    render(<SetupWizard status={BASE} onDone={vi.fn()} />);
    await userEvent.click(screen.getByRole("tab", { name: /run a model locally/i }));

    expect(screen.getByText(/Ollama isn't running/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /get ollama/i })).toHaveAttribute(
      "href",
      "https://ollama.com",
    );
  });

  it("suggests a model that fits the detected hardware", async () => {
    render(<SetupWizard status={BASE} onDone={vi.fn()} />);
    await userEvent.click(screen.getByRole("tab", { name: /run a model locally/i }));

    expect(screen.getByText(/ollama pull qwen2\.5-coder:7b/)).toBeInTheDocument();
  });

  it("saves the selected local model and closes", async () => {
    const onDone = vi.fn();
    render(<SetupWizard status={withOllama(["llama3.2:3b", "phi4"])} onDone={onDone} />);

    await userEvent.selectOptions(screen.getByLabelText("Installed models"), "phi4");
    await userEvent.click(screen.getByRole("button", { name: /start using sensei/i }));

    await waitFor(() =>
      expect(api.applySettings).toHaveBeenCalledWith({ provider: "ollama", model: "phi4" }),
    );
    expect(onDone).toHaveBeenCalled();
  });
});

describe("the hosted path", () => {
  it("loads the provider's live model list rather than a hardcoded one", async () => {
    render(<SetupWizard status={BASE} onDone={vi.fn()} />);

    await waitFor(() => expect(api.getProviderModels).toHaveBeenCalledWith("openrouter"));
    await waitFor(() =>
      expect(screen.getByText(/fetched from OpenRouter just now/i)).toBeInTheDocument(),
    );
  });

  it("says so plainly when the list is a stale fallback", async () => {
    vi.mocked(api.getProviderModels).mockResolvedValue({
      provider: "openrouter",
      models: ["zhipuai/glm-5.2"],
      source: "catalog",
      detail: "Enter an API key to load this provider's live model list.",
    });
    render(<SetupWizard status={BASE} onDone={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByText(/Enter an API key to load/i)).toBeInTheDocument(),
    );
  });

  it("reloads the model list when the provider changes", async () => {
    render(<SetupWizard status={BASE} onDone={vi.fn()} />);
    await waitFor(() => expect(api.getProviderModels).toHaveBeenCalledWith("openrouter"));

    await userEvent.selectOptions(screen.getByLabelText("Provider"), "openai");
    await waitFor(() => expect(api.getProviderModels).toHaveBeenCalledWith("openai"));
  });

  it("will not submit without a key when none is configured yet", () => {
    render(<SetupWizard status={BASE} onDone={vi.fn()} />);
    expect(screen.getByRole("button", { name: /start using sensei/i })).toBeDisabled();
  });

  it("allows submitting with no key when one is already stored", () => {
    render(
      <SetupWizard status={{ ...BASE, configured_providers: ["openrouter"] }} onDone={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: /start using sensei/i })).toBeEnabled();
  });

  it("masks the API key input", async () => {
    render(<SetupWizard status={BASE} onDone={vi.fn()} />);
    expect(screen.getByLabelText("API key")).toHaveAttribute("type", "password");
  });

  it("submits the key and chosen model", async () => {
    const onDone = vi.fn();
    render(<SetupWizard status={BASE} onDone={onDone} />);

    await userEvent.type(screen.getByLabelText("API key"), "sk-secret");
    await waitFor(() => expect(screen.getByLabelText("Provider")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /start using sensei/i }));

    await waitFor(() =>
      expect(api.applySettings).toHaveBeenCalledWith(
        expect.objectContaining({ provider: "openrouter", api_key: "sk-secret" }),
      ),
    );
    expect(onDone).toHaveBeenCalled();
  });

  it("shows the error instead of pretending it worked", async () => {
    vi.mocked(api.applySettings).mockRejectedValue(new Error("API error 401: bad key"));
    const onDone = vi.fn();
    render(<SetupWizard status={BASE} onDone={onDone} />);

    await userEvent.type(screen.getByLabelText("API key"), "sk-bad");
    await userEvent.click(screen.getByRole("button", { name: /start using sensei/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("401");
    expect(onDone).not.toHaveBeenCalled();
  });
});

describe("escape hatch", () => {
  it("can be skipped without configuring anything", async () => {
    const onDone = vi.fn();
    render(<SetupWizard status={BASE} onDone={onDone} />);

    await userEvent.click(screen.getByRole("button", { name: /skip for now/i }));
    expect(onDone).toHaveBeenCalled();
    expect(api.applySettings).not.toHaveBeenCalled();
  });

  it("reports the detected hardware so a wrong guess is visible", () => {
    render(<SetupWizard status={BASE} onDone={vi.fn()} />);
    expect(screen.getByText(/16 cores/)).toBeInTheDocument();
    expect(screen.getByText(/NVIDIA RTX 4080/)).toBeInTheDocument();
  });
});
