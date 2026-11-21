// Microphone level bus. The level changes about 30 times a second, so it is kept out of React state:
// the mic button subscribes and writes a CSS variable directly.
type Listener = (level: number) => void;

const listeners = new Set<Listener>();
let current = 0;

export const micLevel = {
  get value(): number {
    return current;
  },
  emit(level: number): void {
    current = level;
    for (const fn of listeners) fn(level);
  },
  subscribe(fn: Listener): () => void {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
};
