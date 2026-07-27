import { useCallback, type RefObject } from 'react';

function collectStyles(): string {
  const sheets = Array.from(document.styleSheets);
  const rules: string[] = [];
  for (const sheet of sheets) {
    try {
      for (const rule of sheet.cssRules) {
        rules.push(rule.cssText);
      }
    } catch {
      // cross-origin stylesheets are inaccessible
    }
  }
  return rules.join('\n');
}

function cloneSvgWithStyles(container: HTMLElement): SVGElement | null {
  const svg = container.querySelector('.react-flow__viewport')?.closest('svg');
  if (svg === null || svg === undefined) return null;

  const clone = svg.cloneNode(true) as SVGSVGElement;
  const bounds = svg.getBoundingClientRect();
  clone.setAttribute('width', String(bounds.width));
  clone.setAttribute('height', String(bounds.height));
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');

  // Preserve the active theme so dark-mode CSS variable overrides continue to
  // apply inside the detached SVG, and paint a background matching the app.
  const resolvedTheme =
    document.documentElement.dataset.theme ??
    (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  clone.setAttribute('data-theme', resolvedTheme);

  const bgColor = getComputedStyle(document.documentElement)
    .getPropertyValue('--bg')
    .trim();
  const background = document.createElementNS(
    'http://www.w3.org/2000/svg',
    'rect',
  );
  background.setAttribute('width', '100%');
  background.setAttribute('height', '100%');
  background.setAttribute('fill', bgColor || '#ffffff');
  clone.insertBefore(background, clone.firstChild);

  const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style');
  styleEl.textContent = collectStyles();
  clone.insertBefore(styleEl, clone.firstChild);

  // Remove interactive controls and minimap from export
  for (const selector of ['.react-flow__controls', '.react-flow__minimap', '.react-flow__background']) {
    clone.querySelectorAll(selector).forEach((el) => el.remove());
  }

  return clone;
}

function svgToBlob(svg: SVGElement): Blob {
  const serializer = new XMLSerializer();
  const svgString = serializer.serializeToString(svg);
  return new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function useGraphExport(
  containerRef: RefObject<HTMLDivElement | null>,
) {
  const exportSvg = useCallback(() => {
    const container = containerRef.current;
    if (container === null) return;
    const svg = cloneSvgWithStyles(container);
    if (svg === null) return;
    const blob = svgToBlob(svg);
    downloadBlob(blob, 'model-graph.svg');
  }, []);

  const exportPng = useCallback(() => {
    const container = containerRef.current;
    if (container === null) return;
    const svg = cloneSvgWithStyles(container);
    if (svg === null) return;

    const svgBlob = svgToBlob(svg);
    const url = URL.createObjectURL(svgBlob);
    const img = new Image();
    const width = Number(svg.getAttribute('width') ?? 800);
    const height = Number(svg.getAttribute('height') ?? 600);

    img.onload = () => {
      const scale = 2;
      const canvas = document.createElement('canvas');
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext('2d');
      if (ctx === null) {
        URL.revokeObjectURL(url);
        return;
      }
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => {
        if (blob !== null) {
          downloadBlob(blob, 'model-graph.png');
        }
      }, 'image/png');
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
    };
    img.src = url;
  }, []);

  return { exportSvg, exportPng };
}
