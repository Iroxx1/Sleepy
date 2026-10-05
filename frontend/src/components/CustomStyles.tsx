import { useEffect, useState } from "react";

/** Loads admin-wide and personal custom CSS as same-origin stylesheets (CSP friendly). */
export function reloadCustomCss() {
  window.dispatchEvent(new Event("sleepy-css-changed"));
}

function useLink(id: string, href: string | null) {
  useEffect(() => {
    let el = document.getElementById(id) as HTMLLinkElement | null;
    if (!href) {
      el?.remove();
      return;
    }
    if (!el) {
      el = document.createElement("link");
      el.id = id;
      el.rel = "stylesheet";
      document.head.appendChild(el);
    }
    el.href = href;
  }, [id, href]);
}

export default function CustomStyles({ loggedIn }: { loggedIn: boolean }) {
  const [v, setV] = useState(0);
  useEffect(() => {
    const fn = () => setV((x) => x + 1);
    window.addEventListener("sleepy-css-changed", fn);
    return () => window.removeEventListener("sleepy-css-changed", fn);
  }, []);
  useLink("sleepy-global-css", `/api/appearance/global.css?v=${v}`);
  useLink("sleepy-user-css", loggedIn ? `/api/appearance/user.css?v=${v}` : null);
  return null;
}
