import * as Dialog from "@radix-ui/react-dialog";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import * as Popover from "@radix-ui/react-popover";
import * as Tooltip from "@radix-ui/react-tooltip";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Button } from "./ui";

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/35 backdrop-blur-[1px]" />
        <Dialog.Content
          className={cn(
            "enter fixed top-[max(1rem,10vh)] left-1/2 z-50 max-h-[85dvh] w-[min(34rem,calc(100vw-1.5rem))] -translate-x-1/2 overflow-y-auto rounded-xl border border-line bg-paper p-5 shadow-2xl",
            className,
          )}
        >
          <div className="mb-3 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-[16px] font-semibold">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="mt-0.5 text-[13px] text-mut">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">{title}</Dialog.Description>
              )}
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="iconSm" aria-label="Close">
                <X className="size-4" />
              </Button>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Confirm({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  onConfirm,
  busy,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  busy?: boolean;
}) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title} description={body} className="w-[min(26rem,calc(100vw-1.5rem))]">
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="danger" loading={busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}

const panel = "z-50 min-w-44 rounded-lg border border-line bg-raise p-1 shadow-xl enter";
export const Menu = Dropdown.Root;
export const MenuTrigger = Dropdown.Trigger;
export const MenuContent = ({ children, align = "end" }: { children: ReactNode; align?: "start" | "end" }) => (
  <Dropdown.Portal>
    <Dropdown.Content align={align} sideOffset={6} className={panel}>
      {children}
    </Dropdown.Content>
  </Dropdown.Portal>
);
export const MenuItem = ({
  children,
  onSelect,
  danger,
  disabled,
}: {
  children: ReactNode;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
}) => (
  <Dropdown.Item
    onSelect={onSelect}
    disabled={disabled}
    className={cn(
      "flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-[13.5px] outline-none data-[disabled]:opacity-40 data-[highlighted]:bg-panel",
      danger ? "text-bad" : "text-ink",
    )}
  >
    {children}
  </Dropdown.Item>
);

export const Pop = Popover.Root;
export const PopTrigger = Popover.Trigger;
export const PopContent = ({
  children,
  className,
  align = "start",
}: {
  children: ReactNode;
  className?: string;
  align?: "start" | "end";
}) => (
  <Popover.Portal>
    <Popover.Content align={align} sideOffset={6} className={cn(panel, "p-2", className)}>
      {children}
    </Popover.Content>
  </Popover.Portal>
);

export const TooltipProvider = Tooltip.Provider;
export function Tip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Tooltip.Root delayDuration={350}>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content sideOffset={6} className="z-50 rounded-md bg-ink px-2 py-1 text-[12px] text-paper shadow-lg">
          {label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
