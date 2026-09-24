export type PaperInkTheme = {
  paper: string;
  paperDeep: string;
  ink: string;
  inkSoft: string;
  amber: string;
  amberSoft: string;
  rule: string;
  fontFamily: string;
  backgroundOverlay: string;
  panelSurface: string;
  promptSurface: string;
  mutedSurface: string;
  shadow: string;
};

export const PAPER_INK_THEME: PaperInkTheme = {
  paper: "#F4EFE5",
  paperDeep: "#E7DED0",
  ink: "#25211C",
  inkSoft: "#756C60",
  amber: "#B46D22",
  amberSoft: "#E1BE8B",
  rule: "#CFC4B3",
  fontFamily: "sans-serif",
  backgroundOverlay: "rgba(255,255,255,0.12)",
  panelSurface: "rgba(255,253,247,0.68)",
  promptSurface: "rgba(255,253,247,0.78)",
  mutedSurface: "rgba(37,33,28,0.06)",
  shadow: "0 18px 38px rgba(37,33,28,0.10)",
};

export const clamp = (value: number, from = 0, to = 1): number =>
  Math.min(to, Math.max(from, value));

export const paperBackground = (theme: PaperInkTheme): string =>
  `repeating-linear-gradient(0deg, transparent 0px, transparent 41px, ${theme.rule}22 42px), linear-gradient(135deg, ${theme.paper} 0%, ${theme.paperDeep} 100%)`;
