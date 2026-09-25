import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { ExperimentApiService } from './experiment-api.service';
import { HealthResponse } from './api.models';

describe('ExperimentApiService', () => {
  let service: ExperimentApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ExperimentApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.useRealTimers();
  });

  it('requests the relative health endpoint and preserves the backend response', async () => {
    const response: HealthResponse = {
      status: 'ok',
      model: {
        loaded: true,
        name: 'sam2.1_hiera_small',
        device: 'cpu',
        dtype: 'torch.float32',
      },
    };
    const result = firstValueFrom(service.getHealth());
    const request = http.expectOne('/health');
    expect(request.request.method).toBe('GET');
    request.flush(response);
    expect(await result).toEqual(response);
  });

  it('extracts a message from the documented backend error envelope', async () => {
    const result = firstValueFrom(service.getHealth());
    const assertion = expect(result).rejects.toThrow(
      'Segmentation service unavailable.',
    );
    http
      .expectOne('/health')
      .flush(
        {
          error: {
            code: 'service_unavailable',
            message: 'Segmentation service unavailable.',
          },
        },
        { status: 503, statusText: 'Unavailable' },
      );
    await assertion;
  });

  it.each([null, '<html>Bad gateway</html>', { error: { message: 42 } }])(
    'uses a fallback for unexpected error bodies: %j',
    async (body) => {
      const result = firstValueFrom(service.getHealth());
      const assertion = expect(result).rejects.toThrow(
        'Unable to reach the backend',
      );
      http
        .expectOne('/health')
        .flush(body, { status: 502, statusText: 'Bad Gateway' });
      await assertion;
    },
  );

  it('stops a stalled health request after ten seconds', async () => {
    vi.useFakeTimers();
    const result = firstValueFrom(service.getHealth());
    const assertion = expect(result).rejects.toThrow(
      'Unable to reach the backend',
    );
    const request = http.expectOne('/health');
    await vi.advanceTimersByTimeAsync(10000);
    await assertion;
    expect(request.cancelled).toBe(true);
  });
});
