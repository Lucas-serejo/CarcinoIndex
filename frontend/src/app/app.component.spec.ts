import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { App } from './app.component';
import { HealthResponse } from './api/api.models';

describe('Research application shell', () => {
  let fixture: ComponentFixture<App>;
  let http: HttpTestingController;
  let element: HTMLElement;
  const healthy: HealthResponse = {
    status: 'ok',
    model: {
      loaded: true,
      name: 'sam2.1_hiera_small',
      device: 'cuda:0',
      dtype: 'torch.float32',
    },
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(App);
    element = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('renders the research identity, loading state, and unavailable workflow action', () => {
    expect(element.textContent).toContain('CarcinoIndex');
    expect(element.textContent).toContain('Academic research prototype');
    expect(element.querySelector('main h1')).not.toBeNull();
    expect(
      element.querySelector('[role="status"]')?.getAttribute('aria-busy'),
    ).toBe('true');
    expect(element.textContent).toContain('Checking…');
    expect(
      element.querySelector<HTMLButtonElement>('.primary-button')?.disabled,
    ).toBe(true);
    expect(
      element.querySelector<HTMLButtonElement>('.refresh-button')?.disabled,
    ).toBe(true);
    http.expectOne('/health').flush(healthy);
  });

  it('shows the returned model and device after the startup health check', () => {
    http.expectOne('/health').flush(healthy);
    fixture.detectChanges();
    expect(element.querySelector('.status-value')?.textContent).toContain(
      'Ready',
    );
    expect(element.querySelector('.model-name')?.textContent?.trim()).toBe(
      'SAM 2.1 Hiera Small',
    );
    expect(element.querySelector('.model-detail')?.textContent).toContain(
      'cuda:0',
    );
    expect(element.querySelector('.model-detail')?.textContent).toContain(
      'torch.float32',
    );
    expect(
      element.querySelector('[role="status"]')?.getAttribute('aria-busy'),
    ).toBe('false');
    expect(element.textContent).toContain('not clinical validation');
    expect(element.querySelector<HTMLButtonElement>('.primary-button')?.disabled).toBe(false);
  });

  it('distinguishes a reachable backend from a model that is not loaded', () => {
    http
      .expectOne('/health')
      .flush({ ...healthy, model: { ...healthy.model, loaded: false } });
    fixture.detectChanges();
    expect(element.querySelector('.status-value')?.textContent).toContain(
      'Ready',
    );
    expect(element.querySelector('.model-detail')?.textContent).toContain(
      'Not loaded',
    );
    expect(element.querySelector<HTMLButtonElement>('.primary-button')?.disabled).toBe(true);
  });

  it('recovers from a connection failure through the retry button', () => {
    http.expectOne('/health').error(new ProgressEvent('error'));
    fixture.detectChanges();
    expect(element.textContent).toContain('Unavailable');
    expect(element.textContent).toContain('Unable to reach the backend');
    expect(element.querySelector<HTMLButtonElement>('.primary-button')?.disabled).toBe(true);
    const retry = element.querySelector<HTMLButtonElement>('.refresh-button');
    expect(retry?.textContent).toContain('Try again');
    retry?.click();
    fixture.detectChanges();
    expect(element.textContent).toContain('Checking…');
    http.expectOne('/health').flush(healthy);
    fixture.detectChanges();
    expect(element.querySelector('.status-value')?.textContent).toContain(
      'Ready',
    );
    expect(element.textContent).not.toContain('Unable to reach the backend');
  });

  it('clears stale model information when a later health check fails', () => {
    http.expectOne('/health').flush(healthy);
    fixture.detectChanges();
    element.querySelector<HTMLButtonElement>('.refresh-button')?.click();
    http
      .expectOne('/health')
      .flush(
        { error: { code: 'unavailable', message: 'Service unavailable.' } },
        { status: 503, statusText: 'Unavailable' },
      );
    fixture.detectChanges();
    expect(element.querySelector('.model-name')?.textContent?.trim()).toBe(
      'Awaiting model information',
    );
    expect(element.textContent).not.toContain('cuda:0');
    expect(element.textContent).toContain('Service unavailable.');
  });

  it('renders unrecognized model information as text, never executable HTML', () => {
    const markup = '<img src=x onerror="alert(1)">';
    http.expectOne('/health').flush({
      ...healthy,
      model: { ...healthy.model, name: markup, device: markup, dtype: markup },
    });
    fixture.detectChanges();
    expect(element.querySelector('.model-name')?.textContent?.trim()).toBe(markup);
    expect(element.querySelector('.model-detail')?.textContent).toContain(
      markup,
    );
    expect(element.querySelector('.status-panel img')).toBeNull();
  });

  it('renders backend error messages safely', () => {
    const message = '<img src=x onerror="alert(1)">';
    http
      .expectOne('/health')
      .flush(
        { error: { code: 'unavailable', message } },
        { status: 503, statusText: 'Unavailable' },
      );
    fixture.detectChanges();
    expect(element.querySelector('.health-message')?.textContent).toContain(
      message,
    );
    expect(element.querySelector('.health-message img')).toBeNull();
  });

  it('cancels an outstanding request when the shell is destroyed', () => {
    const request = http.expectOne('/health');
    fixture.destroy();
    expect(request.cancelled).toBe(true);
  });

  it('opens the workflow while preserving the application identity', () => {
    http.expectOne('/health').flush(healthy);
    fixture.detectChanges();
    element.querySelector<HTMLButtonElement>('.primary-button')?.click();
    fixture.detectChanges();
    expect(element.querySelector('app-experiment-workflow')).not.toBeNull();
    expect(element.textContent).toContain('Experiment setup');
    expect(element.querySelector('header')?.textContent).toContain('CarcinoIndex');
    expect(element.querySelector('footer')).not.toBeNull();
    http.expectOne('/api/v1/pci/regions').flush({ regions: [] });
  });
});
