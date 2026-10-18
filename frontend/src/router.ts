import { useSyncExternalStore } from "react";

// A minimal history router: same-origin links swap pages without a full
// reload, so the Pi serves the bundle and session check only once.
// The route only changes on navigate()/popstate; filters that rewrite the
// query string with replaceState (see param()) don't remount the page.
let current = location.pathname + location.search;
const listeners = new Set<() => void>();

function publish() {
  current = location.pathname + location.search;
  listeners.forEach((listener) => listener());
}

window.addEventListener("popstate", publish);

export function navigate(href: string) {
  history.pushState(null, "", href);
  publish();
}

export function useRoute() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => current,
  );
}

export function interceptLinks(event: MouseEvent) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  )
    return;
  const link = (event.target as Element).closest?.("a");
  const href = link?.getAttribute("href");
  if (
    !link ||
    !href ||
    href.startsWith("#") ||
    link.target ||
    link.hasAttribute("download") ||
    link.origin !== location.origin
  )
    return;
  event.preventDefault();
  navigate(link.pathname + link.search + link.hash);
}
