import { ChangeDetectionStrategy, Component, computed, input, linkedSignal, output, signal } from '@angular/core';
import { ImageBox, MaskResponse } from '../../../api/api.models';

@Component({
  selector: 'app-segmentation-canvas',
  templateUrl: './segmentation-canvas.component.html',
  styleUrl: './segmentation-canvas.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SegmentationCanvasComponent {
  readonly imageUrl = input.required<string>();
  readonly mask = input<MaskResponse | null>(null);
  readonly disabled = input(false);
  readonly boxChange = output<ImageBox | null>();
  readonly imageFailed = output<void>();
  readonly width = signal(0);
  readonly height = signal(0);
  readonly box = signal<ImageBox | null>(null);
  readonly maskDecodeError = linkedSignal({ source: this.mask, computation: () => false });
  readonly maskError = computed(() => {
    const mask = this.mask();
    if (!mask || !this.width()) return '';
    if (mask.width !== this.width() || mask.height !== this.height()) {
      return 'The segmentation mask dimensions do not match the persisted image.';
    }
    return this.maskDecodeError() ? 'The segmentation mask could not be displayed.' : '';
  });
  readonly maskUrl = computed(() => {
    const mask = this.mask();
    return mask && this.width() && !this.maskError() ? `data:image/png;base64,${mask.data}` : null;
  });
  private drag: { id: number; x: number; y: number; target: SVGSVGElement } | null = null;

  imageLoaded(event: Event): void {
    const image = event.target as HTMLImageElement;
    this.width.set(image.naturalWidth);
    this.height.set(image.naturalHeight);
  }

  maskLoaded(event: Event): void {
    const image = event.target as HTMLImageElement;
    this.maskDecodeError.set(image.naturalWidth !== this.width() || image.naturalHeight !== this.height());
  }

  pointerDown(event: PointerEvent): void {
    if (this.disabled() || !this.width() || !event.isPrimary || event.button !== 0 || this.drag) return;
    const target = event.currentTarget as SVGSVGElement;
    const point = this.point(event, target);
    if (!point) return;
    event.preventDefault();
    this.clearBox();
    this.drag = { id: event.pointerId, ...point, target };
    target.setPointerCapture(event.pointerId);
    this.box.set({ xMin: point.x, yMin: point.y, xMax: point.x, yMax: point.y });
  }

  pointerMove(event: PointerEvent): void {
    const drag = this.drag;
    if (!drag || event.pointerId !== drag.id) return;
    const point = this.point(event, drag.target);
    if (!point) return;
    this.box.set({
      xMin: Math.min(drag.x, point.x), yMin: Math.min(drag.y, point.y),
      xMax: Math.max(drag.x, point.x), yMax: Math.max(drag.y, point.y),
    });
  }

  pointerUp(event: PointerEvent): void {
    if (!this.drag || event.pointerId !== this.drag.id) return;
    this.pointerMove(event);
    const rect = this.drag.target.getBoundingClientRect();
    const box = this.box();
    this.stopDrag();
    // Reject accidental clicks in display pixels, independently of image resolution.
    if (!box || (box.xMax - box.xMin) * rect.width / this.width() < 4 ||
        (box.yMax - box.yMin) * rect.height / this.height() < 4) {
      this.clearBox();
      return;
    }
    this.boxChange.emit(box);
  }

  pointerCancel(event: PointerEvent): void {
    if (this.drag?.id === event.pointerId) this.clearBox();
  }

  clearBox(): void {
    this.stopDrag();
    this.box.set(null);
    this.maskDecodeError.set(false);
    this.boxChange.emit(null);
  }

  private stopDrag(): void {
    const drag = this.drag;
    this.drag = null;
    if (drag?.target.hasPointerCapture(drag.id)) drag.target.releasePointerCapture(drag.id);
  }

  private point(event: PointerEvent, target: SVGSVGElement): { x: number; y: number } | null {
    const rect = target.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    return {
      x: Math.max(0, Math.min(this.width(), (event.clientX - rect.left) * this.width() / rect.width)),
      y: Math.max(0, Math.min(this.height(), (event.clientY - rect.top) * this.height() / rect.height)),
    };
  }
}
