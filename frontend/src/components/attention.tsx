import { ExternalLink, RotateCcw, ClipboardPaste } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { explainError, when } from "@/lib/format";
import { useClarify, useRetry } from "@/lib/queries";
import type { InboxRow } from "@/lib/schemas";
import { safeHref } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import { Button, Chip, Textarea } from "./ui";
import { useToast } from "./toast";

const Pasted = z.object({ text: z.string().trim().min(1, "Paste the text you want Pith to use.") });

/** Retry/recover actions for one failed or waiting item, in plain language. */
export function useRecover() {
  const retry = useRetry();
  const clarify = useClarify();
  const toast = useToast();
  const fail = (e: unknown) => toast(e instanceof ApiError ? e.message : "That did not work.", { bad: true });
  return {
    busy: retry.isPending || clarify.isPending,
    retry: (id: string) => retry.mutate(id, { onSuccess: () => toast("Trying again."), onError: fail }),
    clarify: (id: string, text: string, done?: () => void) =>
      clarify.mutate({ id, text }, { onSuccess: () => (toast("Queued with your text."), done?.()), onError: fail }),
  };
}

export function AttentionCard({
  row,
  compact,
}: {
  row: Pick<InboxRow, "id" | "status" | "error" | "what" | "url" | "submitted_at" | "attempts">;
  compact?: boolean;
}) {
  const why = explainError(row.status, row.error);
  const [pasting, setPasting] = useState(false);
  const rec = useRecover();
  const form = useForm<z.infer<typeof Pasted>>({ resolver: zodResolver(Pasted), defaultValues: { text: "" } });
  const href = safeHref(row.url);
  return (
    <div className="rounded-lg border border-line bg-raise p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={row.status === "failed" ? "bad" : "warn"}>{row.status === "failed" ? "Failed" : "Needs you"}</Chip>
        <span className="text-[12.5px] text-mut">{when(row.submitted_at)}</span>
        {!!row.attempts && row.attempts > 1 && <span className="text-[12.5px] text-mut">· tried {row.attempts} times</span>}
      </div>
      <p className="mt-1.5 line-clamp-2 font-medium break-all">{row.what}</p>
      <p className="mt-0.5 text-[13.5px] text-soft">
        <span className="font-medium">{why.title}.</span> <span className="text-mut">{compact ? "" : why.detail}</span>
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => rec.retry(row.id)} disabled={rec.busy}>
          <RotateCcw className="size-3.5" aria-hidden /> Try again
        </Button>
        {why.canPaste && (
          <Button size="sm" variant={pasting ? "ghost" : "secondary"} onClick={() => setPasting((p) => !p)} aria-expanded={pasting}>
            <ClipboardPaste className="size-3.5" aria-hidden /> Paste text instead
          </Button>
        )}
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium text-soft hover:bg-panel hover:text-ink"
          >
            <ExternalLink className="size-3.5" aria-hidden /> Open original
          </a>
        )}
      </div>
      {pasting && (
        <form
          className="mt-3"
          onSubmit={form.handleSubmit((v) => rec.clarify(row.id, v.text, () => setPasting(false)))}
          aria-label="Paste the content for this item"
        >
          <Textarea
            rows={4}
            aria-label="Text to use instead"
            placeholder="Paste the text of the page or video. It replaces the content Pith could not read."
            {...form.register("text")}
          />
          {form.formState.errors.text && <p className="mt-1 text-[13px] text-bad">{form.formState.errors.text.message}</p>}
          <div className="mt-2 flex justify-end">
            <Button size="sm" variant="primary" type="submit" loading={rec.busy}>
              Use this text
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
