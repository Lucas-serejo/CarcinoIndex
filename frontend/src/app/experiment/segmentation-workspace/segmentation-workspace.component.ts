import { ChangeDetectionStrategy, Component, DestroyRef, inject, input, OnInit, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';
import { EvaluationResponse, ImageBox, PersistedSegmentationResponse } from '../../api/api.models';
import { ExperimentApiService } from '../../api/experiment-api.service';
import { SegmentationCanvasComponent } from './segmentation-canvas/segmentation-canvas.component';

@Component({
  selector: 'app-segmentation-workspace',
  imports: [SegmentationCanvasComponent],
  templateUrl: './segmentation-workspace.component.html',
  styleUrl: './segmentation-workspace.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SegmentationWorkspaceComponent implements OnInit {
  readonly evaluationId = input.required<string>();
  readonly clinicalAssessmentRequested = output<void>();
  private readonly api = inject(ExperimentApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly evaluation = signal<EvaluationResponse | null>(null);
  readonly state = signal<'loading-evaluation' | 'loading-image' | 'ready' | 'finalized' | 'error'>('loading-evaluation');
  readonly imageUrl = signal<string | null>(null);
  readonly error = signal('');
  readonly segmentationError = signal('');
  readonly segmenting = signal(false);
  readonly box = signal<ImageBox | null>(null);
  readonly result = signal<PersistedSegmentationResponse | null>(null);
  private loading = false;

  constructor() { this.destroyRef.onDestroy(() => this.revokeImage()); }

  ngOnInit(): void { void this.load(); }

  async load(): Promise<void> {
    if (this.loading || this.segmenting()) return;
    this.loading = true;
    this.error.set('');
    this.prepareBox(null);
    this.revokeImage();
    try {
      let evaluation = this.evaluation();
      if (!evaluation) {
        this.state.set('loading-evaluation');
        evaluation = await firstValueFrom(this.api.getEvaluation(this.evaluationId()).pipe(takeUntilDestroyed(this.destroyRef)));
        if (this.destroyRef.destroyed) return;
        this.evaluation.set(evaluation);
      }
      if (evaluation.status === 'finalized') {
        this.state.set('finalized');
        return;
      }
      this.state.set('loading-image');
      const blob = await firstValueFrom(this.api.getImageContent(evaluation.image_id).pipe(takeUntilDestroyed(this.destroyRef)));
      if (this.destroyRef.destroyed) return;
      this.imageUrl.set(URL.createObjectURL(blob));
      this.state.set('ready');
    } catch (error: unknown) {
      if (!this.destroyRef.destroyed) {
        this.error.set(error instanceof Error ? error.message : 'Unable to load the workspace. Try again.');
        this.state.set('error');
      }
    } finally { this.loading = false; }
  }

  imageFailed(): void {
    this.error.set('The persisted image could not be displayed. Try loading it again.');
    this.state.set('error');
    this.prepareBox(null);
    this.revokeImage();
  }

  prepareBox(box: ImageBox | null): void {
    if (this.segmenting()) return;
    this.box.set(box);
    this.result.set(null);
    this.segmentationError.set('');
  }

  async segment(): Promise<void> {
    const box = this.box();
    if (!box || this.segmenting() || this.state() !== 'ready' || this.evaluation()?.status !== 'draft') return;
    this.segmenting.set(true);
    this.segmentationError.set('');
    try {
      const result = await firstValueFrom(this.api.createBoxSegmentationAttempt(this.evaluationId(), box)
        .pipe(takeUntilDestroyed(this.destroyRef)));
      if (!this.destroyRef.destroyed) this.result.set(result);
    } catch (error: unknown) {
      if (!this.destroyRef.destroyed) this.segmentationError.set(
        error instanceof Error ? error.message : 'Unable to run segmentation. Try again.',
      );
    } finally {
      if (!this.destroyRef.destroyed) this.segmenting.set(false);
    }
  }

  continueToClinicalAssessment(): void {
    if (this.state() === 'ready' && this.result() && !this.segmenting()) {
      this.clinicalAssessmentRequested.emit();
    }
  }

  private revokeImage(): void {
    const url = this.imageUrl();
    if (url) URL.revokeObjectURL(url);
    this.imageUrl.set(null);
  }
}
