import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { CaseResponse, EvaluationResponse, ImageResponse, Region } from '../api/api.models';
import { ExperimentApiService } from '../api/experiment-api.service';

const pseudonymousCode: ValidatorFn = (control) => {
  const value = (control.value as string).trim();
  return !value ? { required: true } : value.length > 128 ? { maxlength: true } : null;
};

type Stage = 'Creating clinical case' | 'Uploading image' | 'Creating evaluation';

@Component({
  selector: 'app-experiment-workflow',
  imports: [ReactiveFormsModule],
  templateUrl: './experiment-workflow.component.html',
  styleUrl: './experiment-workflow.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExperimentWorkflowComponent {
  private readonly api = inject(ExperimentApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly regions = signal<Region[]>([]);
  readonly regionState = signal<'loading' | 'success' | 'error'>('loading');
  readonly regionError = signal('');
  readonly previewUrl = signal<string | null>(null);
  readonly imageError = signal('');
  readonly clinicalCase = signal<CaseResponse | null>(null);
  readonly image = signal<ImageResponse | null>(null);
  readonly evaluation = signal<EvaluationResponse | null>(null);
  readonly stage = signal<Stage | null>(null);
  readonly failure = signal<{ stage: Stage; message: string } | null>(null);
  readonly form = new FormGroup({
    patientCode: new FormControl('', { nonNullable: true, validators: pseudonymousCode }),
    annotatorCode: new FormControl('', { nonNullable: true, validators: pseudonymousCode }),
    regionId: new FormControl<number | null>(null, Validators.required),
    file: new FormControl<File | null>(null, Validators.required),
  });

  constructor() {
    this.loadRegions();
    this.destroyRef.onDestroy(() => this.revokePreview());
  }

  loadRegions(): void {
    this.regionState.set('loading');
    this.regionError.set('');
    this.api.getRegions().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: ({ regions }) => {
        this.regions.set(regions);
        this.regionState.set(regions.length ? 'success' : 'error');
        if (!regions.length) this.regionError.set('No PCI regions are available. Try again.');
      },
      error: (error: Error) => {
        this.regionError.set(error.message);
        this.regionState.set('error');
      },
    });
  }

  selectImage(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.item(0);
    // Keep the native file input empty so its filename is never rendered.
    input.value = '';
    if (this.stage() || this.image() || !file) return;
    this.revokePreview();
    this.form.controls.file.markAsTouched();
    this.imageError.set('');
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      this.form.controls.file.setValue(null);
      this.imageError.set('Choose a JPEG or PNG image.');
      return;
    }
    this.form.controls.file.setValue(file);
    this.previewUrl.set(URL.createObjectURL(file));
  }

  async submit(): Promise<void> {
    if (this.stage() || this.evaluation()) return;
    this.form.markAllAsTouched();
    const values = this.form.getRawValue();
    if (this.form.invalid || this.regionState() !== 'success' || !values.file || values.regionId === null ||
        !this.regions().some(region => region.region_id === values.regionId)) return;
    this.failure.set(null);
    this.form.disable();
    let stage: Stage = 'Creating clinical case';
    this.stage.set(stage);
    try {
      let clinicalCase = this.clinicalCase();
      if (!clinicalCase) {
        clinicalCase = await firstValueFrom(this.api.createCase({
          anonymous_patient_code: values.patientCode.trim(),
        }).pipe(takeUntilDestroyed(this.destroyRef)));
        if (this.destroyRef.destroyed) return;
        this.clinicalCase.set(clinicalCase);
        this.form.controls.patientCode.setValue(clinicalCase.anonymous_patient_code);
      }
      let image = this.image();
      if (!image) {
        stage = 'Uploading image';
        this.stage.set(stage);
        image = await firstValueFrom(this.api.uploadCaseImage(clinicalCase.case_id, values.file)
          .pipe(takeUntilDestroyed(this.destroyRef)));
        if (this.destroyRef.destroyed) return;
        this.image.set(image);
      }
      stage = 'Creating evaluation';
      this.stage.set(stage);
      const evaluation = await firstValueFrom(this.api.createEvaluation(image.image_id, {
        pci_region_id: values.regionId, annotator_code: values.annotatorCode.trim(),
      }).pipe(takeUntilDestroyed(this.destroyRef)));
      if (this.destroyRef.destroyed) return;
      this.evaluation.set(evaluation);
    } catch (error: unknown) {
      if (!this.destroyRef.destroyed) this.failure.set({
        stage, message: error instanceof Error ? error.message : 'Unable to complete this stage. Try again.',
      });
    } finally {
      if (!this.destroyRef.destroyed) {
        this.stage.set(null);
        if (!this.evaluation()) {
          this.form.enable();
          if (this.clinicalCase()) this.form.controls.patientCode.disable();
          if (this.image()) this.form.controls.file.disable();
        }
      }
    }
  }

  regionName(id: number): string {
    return this.regions().find(region => region.region_id === id)?.display_name ?? '';
  }

  private revokePreview(): void {
    const url = this.previewUrl();
    if (url) URL.revokeObjectURL(url);
    this.previewUrl.set(null);
  }
}
