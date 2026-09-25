import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ExperimentApiService } from './api/experiment-api.service';
import { HealthResponse } from './api/api.models';

type HealthState =
  | { status: 'loading' }
  | { status: 'success'; response: HealthResponse }
  | { status: 'error'; message: string };

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {
  private readonly api = inject(ExperimentApiService);
  private readonly destroyRef = inject(DestroyRef);
  readonly health = signal<HealthState>({ status: 'loading' });

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
