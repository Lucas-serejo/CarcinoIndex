import { PercentPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, input, OnInit, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { EvaluationResponse, FinalizeEvaluationRequest } from '../../api/api.models';
import { ExperimentApiService } from '../../api/experiment-api.service';

const clinicalLs: ValidatorFn = control =>
  Number.isInteger(control.value) && [0, 1, 2, 3].includes(control.value as number) ? null : { clinicalLs: true };
const finiteConfidence: ValidatorFn = control =>
  control.value === null || (typeof control.value === 'number' && Number.isFinite(control.value)) ? null : { confidence: true };

type AssessmentState = 'loading' | 'editing' | 'reviewing' | 'finalizing' | 'finalized' | 'error';

@Component({
  selector: 'app-clinical-assessment',
  imports: [ReactiveFormsModule, PercentPipe],
  templateUrl: './clinical-assessment.component.html',
  styleUrl: './clinical-assessment.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ClinicalAssessmentComponent implements OnInit {
  readonly evaluationId = input.required<string>();
  readonly evaluationFinalized = output<EvaluationResponse>();
  private readonly api = inject(ExperimentApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly state = signal<AssessmentState>('loading');
  readonly evaluation = signal<EvaluationResponse | null>(null);
  readonly review = signal<Readonly<FinalizeEvaluationRequest> | null>(null);
  readonly loadError = signal('');
  readonly finalizationError = signal('');
  readonly lsChoices = [0, 1, 2, 3];
  readonly form = new FormGroup({
    clinicalLs: new FormControl<number | null>(null, [Validators.required, clinicalLs]),
    confidencePercent: new FormControl<number | null>(null, [finiteConfidence, Validators.min(0), Validators.max(100)]),
  });

  ngOnInit(): void { this.retrieveEvaluation(); }

  refreshEvaluation(): void {
    if (this.state() === 'loading' || this.state() === 'finalizing' || this.state() === 'finalized') return;
    this.retrieveEvaluation();
  }

  private retrieveEvaluation(): void {
    this.state.set('loading');
    this.loadError.set('');
    this.api.getEvaluation(this.evaluationId()).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: evaluation => {
        this.evaluation.set(evaluation);
        this.finalizationError.set('');
        if (evaluation.status === 'finalized') this.showFinalized(evaluation);
        else this.state.set(this.review() ? 'reviewing' : 'editing');
      },
      error: (error: Error) => {
        this.loadError.set(error.message);
        this.state.set(this.review() ? 'reviewing' : 'error');
      },
    });
  }

  reviewAssessment(): void {
    if (this.state() !== 'editing') return;
    this.form.markAllAsTouched();
    if (this.form.invalid) return;
    const { clinicalLs, confidencePercent } = this.form.getRawValue();
    this.review.set(Object.freeze({
      clinical_ls: clinicalLs!,
      annotator_confidence: confidencePercent === null ? null : confidencePercent / 100,
    }));
    this.finalizationError.set('');
    this.loadError.set('');
    this.state.set('reviewing');
  }

  backToEdit(): void {
    if (this.state() !== 'reviewing') return;
    this.review.set(null);
    this.state.set('editing');
    this.loadError.set('');
    this.finalizationError.set('');
  }

  finalize(): void {
    const request = this.review();
    if (this.state() !== 'reviewing' || !request || this.evaluation()?.status !== 'draft') return;
    this.state.set('finalizing');
    this.finalizationError.set('');
    this.loadError.set('');
    this.api.finalizeEvaluation(this.evaluationId(), request).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: evaluation => this.showFinalized(evaluation),
      error: (error: Error) => {
        this.finalizationError.set(error.message);
        this.state.set('reviewing');
      },
    });
  }

  private showFinalized(evaluation: EvaluationResponse): void {
    this.evaluation.set(evaluation);
    this.state.set('finalized');
    this.review.set(null);
    this.form.disable();
    this.evaluationFinalized.emit(evaluation);
  }
}
