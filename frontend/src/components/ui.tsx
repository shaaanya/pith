import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { cva, type VariantProps } from "class-variance-authority";
import { AlertTriangle, Check, Loader2 } from "lucide-react";
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";

const button = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-md font-medium whitespace-nowrap transition-colors select-none disabled:opacity-45 disabled:pointer-events-none",
  {
    variants: {
      variant: {
        primary: "bg-acc text-acc-ink hover:brightness-110",
        secondary: "bg-raise text-ink border border-line hover:bg-panel",
        ghost: "text-soft hover:bg-panel hover:text-ink",
        danger: "bg-bad-tint text-bad border border-transparent hover:border-bad",
      },
      size: { sm: "h-7 px-2.5 text-[13px]", md: "h-9 px-3.5 text-[13.5px]", icon: "h-9 w-9", iconSm: "h-7 w-7" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  loading?: boolean;
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, loading, children, disabled, type = "button", ...p },
  ref,
) {
  return (
    <button ref={ref} type={type} disabled={disabled || loading} className={cn(button({ variant, size }), className)} {...p}>
      {loading && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
      {children}
    </button>
  );
});

const field =
  "w-full rounded-md border border-line bg-raise px-3 text-[14px] text-ink placeholder:text-mut transition-colors hover:border-mut focus-visible:border-acc focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-acc/30 disabled:opacity-50";
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn(field, "h-9", className)} {...p} />;
});
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...p },
  ref,
) {
  return <textarea ref={ref} className={cn(field, "py-2 leading-relaxed", className)} {...p} />;
});
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, ...p }, ref) {
  return <select ref={ref} className={cn(field, "h-9 pr-8", className)} {...p} />;
});

export function Label({ children, htmlFor, hint }: { children: ReactNode; htmlFor?: string; hint?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-[13px] font-medium text-soft">
      {children}
      {hint && <span className="ml-1.5 font-normal text-mut">{hint}</span>}
    </label>
  );
}

export const Checkbox = forwardRef<HTMLButtonElement, CheckboxPrimitive.CheckboxProps>(function Checkbox({ className, ...p }, ref) {
  return (
    <CheckboxPrimitive.Root
      ref={ref}
      className={cn(
        "grid size-[18px] shrink-0 place-items-center rounded-[5px] border border-mut bg-raise data-[state=checked]:border-acc data-[state=checked]:bg-acc data-[state=checked]:text-acc-ink",
        className,
      )}
      {...p}
    >
      <CheckboxPrimitive.Indicator>
        <Check className="size-3.5" strokeWidth={3} aria-hidden />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
});

export function Switch(p: SwitchPrimitive.SwitchProps) {
  return (
    <SwitchPrimitive.Root
      className="relative h-[22px] w-10 shrink-0 rounded-full border border-line bg-panel transition-colors data-[state=checked]:border-acc data-[state=checked]:bg-acc"
      {...p}
    >
      <SwitchPrimitive.Thumb className="block size-4 translate-x-[2px] rounded-full bg-mut shadow-sm transition-transform data-[state=checked]:translate-x-[20px] data-[state=checked]:bg-acc-ink" />
    </SwitchPrimitive.Root>
  );
}

const chip = cva("inline-flex items-center gap-1 rounded-full px-2 py-px text-[12px] font-medium leading-5 whitespace-nowrap", {
  variants: {
    tone: {
      neutral: "bg-panel text-soft",
      accent: "bg-acc-tint text-acc",
      ok: "bg-ok-tint text-ok",
      warn: "bg-warn-tint text-warn",
      bad: "bg-bad-tint text-bad",
      outline: "border border-line text-soft",
    },
  },
  defaultVariants: { tone: "neutral" },
});
export function Chip({ tone, className, children }: VariantProps<typeof chip> & { className?: string; children: ReactNode }) {
  return <span className={cn(chip({ tone }), className)}>{children}</span>;
}

export const Kbd = ({ children }: { children: ReactNode }) => (
  <kbd className="inline-grid min-w-5 place-items-center rounded border border-line bg-raise px-1 font-sans text-[11px] leading-[18px] text-mut">
    {children}
  </kbd>
);

export const Skeleton = ({ className }: { className?: string }) => (
  <div aria-hidden className={cn("pulse rounded-md bg-panel", className)} />
);

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-mut">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 pb-4">
      <div className="min-w-0">
        <h1 className="text-[22px] leading-tight font-semibold tracking-[-0.01em]">{title}</h1>
        {sub && <p className="mt-0.5 text-[13.5px] text-mut">{sub}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function SectionTitle({ children, count, actions }: { children: ReactNode; count?: number; actions?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-3">
      <h2 className="flex items-baseline gap-2 text-[12px] font-semibold tracking-[0.06em] text-mut uppercase">
        {children}
        {count !== undefined && <span className="font-normal tracking-normal text-mut tabular-nums">{count.toLocaleString()}</span>}
      </h2>
      {actions}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="grid place-items-center px-6 py-14 text-center">
      <div className="max-w-sm">
        <p className="font-serif text-[18px] text-ink">{title}</p>
        {children && <p className="mt-1.5 text-[13.5px] text-mut">{children}</p>}
        {action && <div className="mt-4 flex justify-center gap-2">{action}</div>}
      </div>
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof ApiError ? error.message : "Something went wrong.";
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-bad/40 bg-bad-tint p-4 text-bad">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{msg}</p>
      </div>
      {retry && (
        <Button size="sm" variant="secondary" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}
