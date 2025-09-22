import { useEffect } from "react";

export function useKeypress(key: string, handler: (e: KeyboardEvent) => void) {
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === key.toLowerCase()) handler(e);
    };
    window.addEventListener("keydown", f);
    return () => window.removeEventListener("keydown", f);
  }, [key, handler]);
}

