/** Join CSS class names, skipping missing ones (CSS module lookups can be undefined). */
export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}
