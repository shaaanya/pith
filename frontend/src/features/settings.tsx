import { Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useToast } from "@/components/toast";
import { Button, Chip, ErrorState, Input, Label, PageHeader, Select, Skeleton, Switch } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { getTheme, setTheme, type Theme } from "@/lib/local";
import { detectModels, useAppState, useConfig, usePrivacy, useSaveConfig } from "@/lib/queries";
import type { Config } from "@/lib/schemas";

const NUMERIC = new Set(["context_window", "timeout", "max_tokens"]);
const NAME = /^[A-Za-z0-9_-]{1,32}$/;

const FormSchema = z
  .object({
    allow_remote: z.boolean(),
    backends: z.array(
      z.object({
        name: z.string().regex(NAME, "Use letters, digits, - and _ (up to 32)."),
        type: z.string(),
        editable: z.boolean(),
        raw: z.record(z.string(), z.unknown()),
        fields: z.record(z.string(), z.string()),
      }),
    ),
    tasks: z.record(z.string(), z.string()),
  })
  .superRefine((v, ctx) => {
    const names = v.backends.map((b) => b.name);
    if (new Set(names).size !== names.length) ctx.addIssue({ code: "custom", path: ["backends"], message: "Two models share a name." });
    v.backends.forEach(
      (b, i) =>
        b.editable &&
        Object.entries(b.fields).forEach(([k, val]) => {
          if (NUMERIC.has(k) && val.trim() !== "" && !Number.isFinite(Number(val)))
            ctx.addIssue({ code: "custom", path: ["backends", i, "fields", k], message: "Enter a number." });
        }),
    );
    for (const [task, refs] of Object.entries(v.tasks)) {
      for (const r of refs
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean)) {
        if (!names.includes(r.split(":")[0] ?? ""))
          ctx.addIssue({ code: "custom", path: ["tasks", task], message: `“${r}” is not one of your models.` });
      }
    }
  });
type FormValues = z.infer<typeof FormSchema>;

const toForm = (c: Config): FormValues => ({
  allow_remote: c.allow_remote,
  backends: Object.entries(c.backends).map(([name, b]) => ({
    name,
    type: String(b.spec.type ?? ""),
    editable: b.editable,
    raw: b.spec,
    fields: Object.fromEntries(
      (c.types[String(b.spec.type)] ?? [])
        .filter((k) => k !== "type" && k !== "capabilities")
        .map((k) => [k, b.spec[k] == null ? "" : String(b.spec[k])]),
    ),
  })),
  tasks: Object.fromEntries(c.task_names.map((t) => [t, (c.tasks[t] ?? []).join(", ")])),
});

export function Settings() {
  const cfg = useConfig();
  useEffect(() => {
    document.title = "Settings · Pith";
  }, []);
  return (
    <div className="enter mx-auto max-w-3xl">
      <PageHeader title="Settings" sub="How Pith reads what you save, and where your data lives." />
      <Appearance />
      {cfg.isPending ? (
        <div aria-busy className="mt-8 space-y-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      ) : cfg.isError ? (
        <div className="mt-8">
          <ErrorState error={cfg.error} retry={() => void cfg.refetch()} />
        </div>
      ) : (
        <ModelsForm cfg={cfg.data} />
      )}
      <Capture />
      <Data path={cfg.data?.path} />
    </div>
  );
}

const Section = ({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) => (
  <section className="mt-9 border-t border-hair pt-6">
    <h2 className="text-[16px] font-semibold">{title}</h2>
    {hint && <p className="mt-0.5 mb-4 max-w-[60ch] text-[13.5px] text-mut">{hint}</p>}
    {children}
  </section>
);

function Appearance() {
  const [t, setT] = useState<Theme>(getTheme);
  return (
    <section>
      <h2 className="text-[16px] font-semibold">Appearance</h2>
      <div className="mt-3 max-w-xs">
        <Label htmlFor="theme">Theme</Label>
        <Select
          id="theme"
          value={t}
          onChange={(e) => {
            const v = e.target.value as Theme;
            setT(v);
            setTheme(v);
          }}
        >
          <option value="system">Match my device</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </Select>
      </div>
    </section>
  );
}

function ModelsForm({ cfg }: { cfg: Config }) {
  const save = useSaveConfig();
  const toast = useToast();
  const privacy = usePrivacy();
  const initial = useMemo(() => toForm(cfg), [cfg]);
  const form = useForm<FormValues>({ resolver: zodResolver(FormSchema), defaultValues: initial });
  const { fields, append, remove } = useFieldArray({ control: form.control, name: "backends" });
  const [models, setModels] = useState<Record<number, string[]>>({});
  useEffect(() => form.reset(initial), [initial, form]);

  const onSubmit = form.handleSubmit((v) => {
    const backends: Record<string, Record<string, unknown>> = {};
    for (const b of v.backends) {
      if (!b.editable) {
        backends[b.name] = b.raw;
        continue;
      }
      const spec: Record<string, unknown> = { ...(b.raw.capabilities ? { capabilities: b.raw.capabilities } : {}), type: b.type };
      for (const [k, val] of Object.entries(b.fields)) if (val.trim() !== "") spec[k] = NUMERIC.has(k) ? Number(val) : val.trim();
      backends[b.name] = spec;
    }
    const tasks = Object.fromEntries(
      Object.entries(v.tasks)
        .map(([t, s]) => [
          t,
          s
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
        ])
        .filter(([, r]) => (r as string[]).length),
    );
    save.mutate(
      { backends, tasks, allow_remote: v.allow_remote },
      {
        onSuccess: () => toast("Settings saved. New items use them straight away."),
        onError: (e) => toast(e instanceof ApiError ? e.message : "Could not save.", { bad: true }),
      },
    );
  });

  const addBackend = (preset: string) => {
    const p = cfg.presets[preset] ?? {};
    const type = String(p.type ?? "openai_compat");
    append({
      name: `${preset}${fields.length + 1}`,
      type,
      editable: true,
      raw: {},
      fields: Object.fromEntries(
        (cfg.types[type] ?? []).filter((k) => k !== "type" && k !== "capabilities").map((k) => [k, p[k] == null ? "" : String(p[k])]),
      ),
    });
  };
  const detect = async (i: number) => {
    const url = form.getValues(`backends.${i}.fields.base_url`) ?? "";
    try {
      const r = await detectModels(url);
      setModels((m) => ({ ...m, [i]: r.models }));
      toast(
        r.models.length
          ? `${r.models.length} model(s) found. Click the Model field to choose.`
          : "The server answered but lists no models.",
      );
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Could not reach that server.", { bad: true });
    }
  };

  const errors = form.formState.errors;
  return (
    <form onSubmit={onSubmit} noValidate>
      <Section
        title="Models"
        hint="Pith uses a model to pull the facts out of what you save. With none, it still stores and searches your text. Keys are read from environment variables, never stored here."
      >
        <div className="space-y-4">
          {fields.map((f, i) => {
            const editable = form.watch(`backends.${i}.editable`);
            const type = form.watch(`backends.${i}.type`);
            const keys = Object.keys(f.fields);
            return (
              <fieldset key={f.id} className="rounded-xl border border-line bg-raise p-4">
                <legend className="sr-only">Model {f.name}</legend>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <Input
                    aria-label="Model name"
                    className="h-8 w-40 font-medium"
                    disabled={!editable || Object.keys(cfg.backends).includes(f.name)}
                    {...form.register(`backends.${i}.name`)}
                  />
                  <Chip tone="neutral">{type}</Chip>
                  {String(f.raw.locality ?? "") === "remote" || type === "anthropic" ? (
                    <Chip tone="warn">sends text off this device</Chip>
                  ) : (
                    <Chip tone="ok">on this device</Chip>
                  )}
                  {editable && !Object.keys(cfg.backends).includes(f.name) && (
                    <Button size="iconSm" variant="ghost" className="ml-auto" aria-label={`Remove ${f.name}`} onClick={() => remove(i)}>
                      <Trash2 className="size-4" />
                    </Button>
                  )}
                </div>
                {!editable ? (
                  <p className="text-[13.5px] text-mut">This model is set up in the config file and kept as it is.</p>
                ) : keys.length === 0 ? (
                  <p className="text-[13.5px] text-mut">Nothing to configure.</p>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {keys.map((k) => (
                      <div key={k}>
                        <Label htmlFor={`f-${f.id}-${k}`}>{k.replaceAll("_", " ")}</Label>
                        <Input
                          id={`f-${f.id}-${k}`}
                          list={k === "model" ? `models-${i}` : undefined}
                          autoComplete="off"
                          spellCheck={false}
                          {...form.register(`backends.${i}.fields.${k}`)}
                        />
                        {errors.backends?.[i]?.fields?.[k] && (
                          <p className="mt-1 text-[13px] text-bad">{errors.backends[i]?.fields?.[k]?.message}</p>
                        )}
                      </div>
                    ))}
                    {keys.includes("base_url") && (
                      <div className="flex items-end">
                        <Button onClick={() => void detect(i)}>Find installed models</Button>
                        <datalist id={`models-${i}`}>
                          {models[i]?.map((m) => (
                            <option key={m} value={m} />
                          ))}
                        </datalist>
                      </div>
                    )}
                  </div>
                )}
                {errors.backends?.[i]?.name && <p className="mt-2 text-[13px] text-bad">{errors.backends[i]?.name?.message}</p>}
              </fieldset>
            );
          })}
          {errors.backends && "message" in errors.backends && <p className="text-[13px] text-bad">{String(errors.backends.message)}</p>}
          <div className="flex flex-wrap gap-2">
            {Object.keys(cfg.presets).map((p) => (
              <Button key={p} size="sm" onClick={() => addBackend(p)}>
                <Plus className="size-3.5" aria-hidden /> Add a {p === "local" ? "local" : p === "cloud" ? "cloud (API key)" : p} model
              </Button>
            ))}
          </div>
        </div>
      </Section>

      <Section title="What each job uses" hint="Models are tried in order; the first that works wins. Leave a job empty to skip it.">
        <div className="space-y-3">
          {cfg.task_names.map((t) => (
            <div key={t} className="grid items-start gap-x-4 gap-y-1 sm:grid-cols-[9rem_1fr]">
              <Label htmlFor={`t-${t}`}>{TASK_LABEL[t] ?? t}</Label>
              <div>
                <Input id={`t-${t}`} placeholder="model names, comma separated" autoComplete="off" {...form.register(`tasks.${t}`)} />
                {errors.tasks?.[t] && <p className="mt-1 text-[13px] text-bad">{errors.tasks[t]?.message}</p>}
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Privacy" hint="Text only leaves this device when you allow it and a remote model is in use.">
        <Controller
          control={form.control}
          name="allow_remote"
          render={({ field }) => (
            <div className="flex max-w-xl items-start gap-3">
              <Switch id="allow-remote" checked={field.value} onCheckedChange={field.onChange} />
              <label htmlFor="allow-remote">
                <span className="block font-medium">Allow remote models</span>
                <span className="block text-[13.5px] text-mut">When off, remote models are ignored and nothing leaves your machine.</span>
              </label>
            </div>
          )}
        />
        {privacy.data?.egress?.routes && (
          <dl className="mt-4 grid max-w-xl grid-cols-[8rem_1fr] gap-x-4 gap-y-1.5 text-[13.5px]">
            {Object.entries(privacy.data.egress.routes)
              .filter(([, r]) => r.local.length + r.remote.length > 0)
              .map(([t, r]) => (
                <div key={t} className="contents">
                  <dt className="text-mut">{TASK_LABEL[t] ?? t}</dt>
                  <dd>
                    {r.blocked ? (
                      <span className="text-bad">blocked: remote only, remote is off</span>
                    ) : r.remote.length ? (
                      <span className="text-warn">may send text to {r.remote.join(", ")}</span>
                    ) : (
                      <span className="text-ok">stays on this device</span>
                    )}
                  </dd>
                </div>
              ))}
          </dl>
        )}
      </Section>

      <div className="sticky bottom-[4.25rem] z-10 mt-8 flex items-center gap-3 rounded-xl border border-line bg-paper/95 p-3 backdrop-blur md:bottom-4">
        <Button variant="primary" type="submit" loading={save.isPending} disabled={!form.formState.isDirty}>
          Save settings
        </Button>
        <Button disabled={!form.formState.isDirty} onClick={() => form.reset(initial)}>
          Discard changes
        </Button>
        {form.formState.isDirty && <span className="text-[13px] text-mut">Unsaved changes</span>}
      </div>
    </form>
  );
}

const TASK_LABEL: Record<string, string> = {
  distill: "Writing notes",
  classify: "Choosing topics",
  answer: "Answering questions",
  embed: "Search by meaning",
  rerank: "Ranking results",
  ocr: "Reading images",
  transcribe: "Transcribing audio",
  describe: "Describing images",
};

function Capture() {
  const s = useAppState();
  const c = s.data?.capture;
  return (
    <Section
      title="Capture"
      hint="Where things come in from. These are set in the config file and need Pith to be restarted to change; they cannot be edited here."
    >
      <dl className="grid max-w-xl grid-cols-[9rem_1fr] gap-x-4 gap-y-2 text-[13.5px]">
        <dt className="text-mut">Drop folder</dt>
        <dd className="font-mono text-[12.5px] break-all">{c ? (c.watch.length ? c.watch.join("\n") : "none") : "…"}</dd>
        <dt className="text-mut">Share endpoint</dt>
        <dd className="font-mono text-[12.5px]">{c ? `http://${c.http}` : "…"}</dd>
        <dt className="text-mut">This page</dt>
        <dd>
          Paste, drop or attach anywhere. Press <kbd className="rounded border border-line px-1 font-sans text-[11px]">n</kbd>.
        </dd>
      </dl>
    </Section>
  );
}

function Data({ path }: { path?: string }) {
  return (
    <Section title="Your data" hint="Everything stays in one folder on this machine. These actions run in a terminal, not from this page.">
      <dl className="grid max-w-2xl grid-cols-[9rem_1fr] gap-x-4 gap-y-2 text-[13.5px]">
        <dt className="text-mut">Config file</dt>
        <dd className="font-mono text-[12.5px] break-all">{path ?? "…"}</dd>
        <dt className="text-mut">Back up</dt>
        <dd className="font-mono text-[12.5px]">pith backup</dd>
        <dt className="text-mut">Export to Markdown</dt>
        <dd className="font-mono text-[12.5px]">pith export</dd>
        <dt className="text-mut">Check health</dt>
        <dd className="font-mono text-[12.5px]">pith doctor</dd>
      </dl>
    </Section>
  );
}
