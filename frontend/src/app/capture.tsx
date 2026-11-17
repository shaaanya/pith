import { Paperclip, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { Modal } from "@/components/overlay";
import { useToast } from "@/components/toast";
import { Button, Label, Textarea, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useSubmit } from "@/lib/queries";

const Schema = z.object({
  text: z.string().trim().max(200_000, "That is too long to save in one go."),
  context: z.string().trim().max(2000),
});
type Form = z.infer<typeof Schema>;

const Ctx = createContext<{ open: () => void; saveFiles: (f: File[]) => void; saveText: (t: string, why?: string) => Promise<boolean> }>({
  open: () => undefined,
  saveFiles: () => undefined,
  saveText: async () => false,
});
export const useCapture = () => useContext(Ctx);

/** Capture dialog + drop-anywhere upload. Everything goes through POST /api/inbox. */
export function CaptureProvider({ children }: { children: ReactNode }) {
  const [isOpen, setOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const submit = useSubmit();
  const toast = useToast();

  const report = useCallback(
    (r: { duplicate?: boolean }) => toast(r.duplicate ? "Already saved. Pith will not read it twice." : "Saved. Pith is reading it now."),
    [toast],
  );
  const fail = useCallback((e: unknown) => toast(e instanceof ApiError ? e.message : "Could not save that.", { bad: true }), [toast]);

  const saveFiles = useCallback(
    (files: File[]) => {
      for (const file of files) submit.mutate({ file }, { onSuccess: report, onError: fail });
    },
    [submit, report, fail],
  );
  const saveText = useCallback(
    (text: string, context?: string) =>
      new Promise<boolean>((resolve) =>
        submit.mutate({ text, context }, { onSuccess: (r) => (report(r), resolve(true)), onError: (e) => (fail(e), resolve(false)) }),
      ),
    [submit, report, fail],
  );

  // Drop a file anywhere on the page.
  useEffect(() => {
    let depth = 0;
    const hasFiles = (e: DragEvent) => !!e.dataTransfer?.types.includes("Files");
    const enter = (e: DragEvent) => hasFiles(e) && (depth++, setDragging(true));
    const leave = (e: DragEvent) => hasFiles(e) && ((depth = Math.max(0, depth - 1)), depth === 0 && setDragging(false));
    const over = (e: DragEvent) => hasFiles(e) && e.preventDefault();
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      setDragging(false);
      saveFiles([...(e.dataTransfer?.files ?? [])]);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, [saveFiles]);

  const value = useMemo(() => ({ open: () => setOpen(true), saveFiles, saveText }), [saveFiles, saveText]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <CaptureDialog open={isOpen} onOpenChange={setOpen} />
      {dragging && (
        <div
          aria-hidden
          className="pointer-events-none fixed inset-3 z-[70] grid place-items-center rounded-2xl border-2 border-dashed border-acc bg-paper/85 text-[18px] font-medium text-acc"
        >
          Drop to save
        </div>
      )}
    </Ctx.Provider>
  );
}

function CaptureDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { saveFiles, saveText } = useCapture();
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const form = useForm<Form>({ resolver: zodResolver(Schema), defaultValues: { text: "", context: "" } });

  useEffect(() => {
    if (!open) {
      form.reset();
      setFiles([]);
    }
  }, [open, form]);

  const onSubmit = form.handleSubmit(async (v) => {
    if (!v.text && files.length === 0) {
      form.setError("text", { message: "Paste a link or some text, or attach a file." });
      return;
    }
    setBusy(true);
    let ok = true;
    if (v.text) ok = await saveText(v.text, v.context || undefined);
    if (ok && files.length) saveFiles(files);
    setBusy(false);
    if (ok) onOpenChange(false);
  });

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Save something"
      description="Paste a link or text, or attach a file. Pith reads it in the background."
    >
      <form onSubmit={onSubmit} className="space-y-3.5">
        <div>
          <Label htmlFor="cap-text">Link or text</Label>
          <Textarea
            id="cap-text"
            rows={4}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- the dialog exists to type into this field
            autoFocus
            placeholder="https://… or paste text"
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void onSubmit();
            }}
            {...form.register("text")}
          />
          {form.formState.errors.text && <p className="mt-1 text-[13px] text-bad">{form.formState.errors.text.message}</p>}
        </div>
        <div>
          <Label htmlFor="cap-why" hint="optional">
            Why are you saving it?
          </Label>
          <Input id="cap-why" placeholder="What do you want to get out of it later?" {...form.register("context")} />
        </div>
        <div>
          <input
            ref={picker}
            type="file"
            multiple
            hidden
            onChange={(e) => setFiles([...files, ...(e.target.files ?? [])])}
            aria-label="Attach files"
          />
          <Button onClick={() => picker.current?.click()}>
            <Paperclip className="size-4" aria-hidden /> Attach files
          </Button>
          {files.length > 0 && (
            <ul className="mt-2 space-y-1">
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`} className="flex items-center justify-between rounded-md bg-panel px-2.5 py-1 text-[13px]">
                  <span className="truncate">{f.name}</span>
                  <button
                    type="button"
                    aria-label={`Remove ${f.name}`}
                    className="text-mut hover:text-ink"
                    onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  >
                    <X className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex items-center justify-between pt-1">
          <span className="text-[12.5px] text-mut">⌘↵ to save</span>
          <Button variant="primary" type="submit" loading={busy}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}
