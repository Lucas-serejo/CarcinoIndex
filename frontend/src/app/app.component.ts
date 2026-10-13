import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ExperimentApiService } from './api/experiment-api.service';
import { HealthResponse } from './api/api.models';
import { ExperimentWorkflowComponent } from './experiment/experiment-workflow.component';

type HealthState =
  | { status: 'loading' }
  | { status: 'success'; response: HealthResponse }
  | { status: 'error'; message: string };

@Component({
  selector: 'app-root',
  imports: [ExperimentWorkflowComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {
  private readonly api = inject(ExperimentApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly health = signal<HealthState>({ status: 'loading' });
  readonly screen = signal<'overview' | 'workflow'>('overview');
  readonly canStart = computed(() => {
    const health = this.health();
    return health.status === 'success' && health.response.model.loaded;
  });

  startEvaluation(): void {
    if (this.canStart()) this.screen.set('workflow');
  }

  constructor() {
    this.checkHealth();
  }

  checkHealth(): void {
    this.health.set({ status: 'loading' });
    this.api
      .getHealth()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (response) => this.health.set({ status: 'success', response }),
        error: (error: unknown) =>
          this.health.set({
            status: 'error',
            message:
              error instanceof Error
                ? error.message
                : 'Backend unavailable. Try again.',
          }),
      });
  }

  modelName(name: string): string {
    return name === 'sam2.1_hiera_small' ? 'SAM 2.1 Hiera Small' : name;
  }
}
