import axios, { AxiosInstance } from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

const DEFAULT_API_BASE = 'https://samvara-api.fly.dev';

interface ApiClientConfig {
  baseURL?: string;
}

class ApiClient {
  private client: AxiosInstance;
  private token: string | null = null;

  constructor(config?: ApiClientConfig) {
    const baseURL = config?.baseURL || DEFAULT_API_BASE;

    this.client = axios.create({
      baseURL,
      timeout: 15000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Request interceptor to add auth token
    this.client.interceptors.request.use((config) => {
      if (this.token) {
        config.headers.Authorization = `Bearer ${this.token}`;
      }
      return config;
    });

    // Response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response?.status === 401) {
          // Token expired or invalid
          this.token = null;
          AsyncStorage.removeItem('apiToken');
        }
        return Promise.reject(error.response?.data || error);
      }
    );
  }

  setToken(token: string | null) {
    this.token = token;
  }

  // Auth endpoints
  async sendCode(email: string) {
    return this.client.post('/v1/auth/send-code', { email });
  }

  async verifyCode(email: string, code: string) {
    return this.client.post('/v1/auth/verify-code', { email, code });
  }

  async signOut() {
    return this.client.post('/v1/auth/sign-out');
  }

  // Commitment endpoints
  async getCommitments() {
    return this.client.get('/v1/commitments');
  }

  async getCommitment(id: string) {
    return this.client.get(`/v1/commitments/${id}`);
  }

  async createCommitment(data: any) {
    return this.client.post('/v1/commitments', data);
  }

  async confirmClean(id: string) {
    return this.client.post(`/v1/commitments/${id}/confirm-clean`);
  }

  async slip(id: string, data: any) {
    return this.client.post(`/v1/commitments/${id}/slip`, data);
  }

  async miss(id: string, data: any) {
    return this.client.post(`/v1/commitments/${id}/miss`, data);
  }

  async autoMiss(id: string) {
    return this.client.post(`/v1/commitments/${id}/auto-miss`);
  }

  async chooseNext(id: string, data: any) {
    return this.client.post(`/v1/commitments/${id}/choose-next`, data);
  }

  // Metrics endpoints
  async getMetrics() {
    return this.client.get('/v1/metrics');
  }

  async bumpMetric(key: string, delta: number) {
    return this.client.post(`/v1/metrics/${key}/bump`, { delta });
  }

  // Settings endpoints
  async getSettings() {
    return this.client.get('/v1/settings');
  }

  async updateSettings(data: any) {
    return this.client.patch('/v1/settings', data);
  }

  // Notifications endpoints
  async getNotifications(unreadOnly?: boolean) {
    return this.client.get('/v1/notifications', {
      params: { unread_only: unreadOnly || false }
    });
  }

  async getNotification(id: string) {
    return this.client.get(`/v1/notifications/${id}`);
  }

  async markNotificationRead(id: string) {
    return this.client.post(`/v1/notifications/${id}/read`);
  }

  async markAllNotificationsRead() {
    return this.client.post('/v1/notifications/read-all');
  }

  // Sessions endpoints
  async getSessions() {
    return this.client.get('/v1/sessions');
  }

  async revokeDevice(deviceId: string) {
    return this.client.delete(`/v1/sessions/${deviceId}`);
  }

  async revokeAllSessions() {
    return this.client.delete('/v1/sessions');
  }

  // Audit log endpoints
  async getAuditLog(limit?: number) {
    return this.client.get('/v1/audit-log', {
      params: { limit: limit || 50 }
    });
  }

  // Data export endpoints
  async exportUserData() {
    return this.client.get('/v1/data-export');
  }

  // Billing endpoints — Stripe is the only charge provider ordinary users
  // ever see; there is no client-side path to the hidden Beeminder option.
  async getBillingStatus() {
    return this.client.get('/v1/billing/status');
  }

  async createSetupIntent() {
    return this.client.post('/v1/billing/setup-intent');
  }

  async savePaymentMethod(setupIntentId: string) {
    return this.client.post('/v1/billing/payment-method', { setupIntentId });
  }

  // Health check
  async health() {
    return this.client.get('/v1/health');
  }
}

export const apiClient = new ApiClient();
