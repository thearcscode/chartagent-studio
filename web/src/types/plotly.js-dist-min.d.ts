/** plotly.js-dist-min ships no types; this is the narrow slice Studio uses. */
declare module "plotly.js-dist-min" {
  export function newPlot(
    el: HTMLElement,
    data: unknown[],
    layout?: unknown,
    config?: unknown,
  ): Promise<unknown>;
  export function purge(el: HTMLElement): void;
}
