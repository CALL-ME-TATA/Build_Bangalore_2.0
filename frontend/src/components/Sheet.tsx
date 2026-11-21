// Bottom sheet built on vaul (Radix Dialog underneath), as drawn on the Doubt board: scrim, white sheet with
// 24px top corners and its own soft shadow, a 40 x 4 grabber. Modal, focus trapped inside; Esc, a tap on the
// scrim or a swipe down closes it. Elements marked data-vaul-no-drag (the talk control) never start a drag.
//
// Focus: `initialFocus` receives focus when the sheet opens; on close, focus returns to the first visible
// element of `returnFocusIds` (default: the phone mic, then the desktop mic).
import { Drawer } from 'vaul';
import type { ReactNode, RefObject } from 'react';

export interface SheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Accessible title of the dialog (visually hidden; render the visible heading in `children`). */
  title: ReactNode;
  description?: ReactNode;
  initialFocus?: RefObject<HTMLElement | null>;
  returnFocusIds?: string[];
  children: ReactNode;
}

function focusFirstVisible(ids: string[]) {
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el && el.offsetParent !== null) {
      el.focus();
      return;
    }
  }
}

export function Sheet({ open, onOpenChange, title, description, initialFocus, returnFocusIds = ['mic-main', 'mic-desk', 'mic-mini'], children }: SheetProps) {
  return (
    <Drawer.Root open={open} onOpenChange={onOpenChange} repositionInputs={false}>
      <Drawer.Portal>
        <Drawer.Overlay className="sheet-overlay" />
        <Drawer.Content
          className="sheet-content"
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            initialFocus?.current?.focus();
          }}
          onCloseAutoFocus={(e) => {
            e.preventDefault();
            focusFirstVisible(returnFocusIds);
          }}
        >
          <div className="flex justify-center pt-3">
            <Drawer.Handle className="sheet-handle" />
          </div>
          <Drawer.Title className="sr-only">{title}</Drawer.Title>
          <Drawer.Description className="sr-only">{description ?? title}</Drawer.Description>
          <div className="overflow-y-auto px-6 pt-[1.375rem] pb-[2.125rem]">{children}</div>
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  );
}
