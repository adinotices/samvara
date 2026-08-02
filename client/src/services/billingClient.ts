/**
 * Billing service client with retry logic, error handling, and offline support.
 * Wraps apiClient methods with resilience patterns for production reliability.
 */

import { apiClient } from './apiClient';
import AsyncStorage from '@react-native-async-storage/async-storage';

export interface BillingError {
  type: 'network' | 'validation' | 'server' | 'user_action' | 'unknown';
  message: string;
  userMessage: string; // Safe to show to user
  retryable: boolean;
  originalError?: any;
}

interface RetryConfig {
  maxRetries: number;
  initialDelayMs: number;
  maxDelayMs: number;
  backoffMultiplier: number;
}

const DEFAULT_RETRY_CONFIG: RetryConfig = {
  maxRetries: 3,
  initialDelayMs: 1000, // 1 second
  maxDelayMs: 10000, // 10 seconds
  backoffMultiplier: 2,
};

/**
 * Retry a function with exponential backoff.
 * Respects retry config and catches all error types.
 */
async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  config: Partial<RetryConfig> = {}
): Promise<T> {
  const fullConfig = { ...DEFAULT_RETRY_CONFIG, ...config };
  let lastError: any;
  let delay = fullConfig.initialDelayMs;

  for (let attempt = 0; attempt <= fullConfig.maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;

      // Don't retry on last attempt
      if (attempt === fullConfig.maxRetries) {
        throw error;
      }

      // Don't retry non-retryable errors
      if (isNonRetryable(error)) {
        throw error;
      }

      // Wait before retry
      await sleep(delay);
      delay = Math.min(delay * fullConfig.backoffMultiplier, fullConfig.maxDelayMs);
    }
  }

  throw lastError;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function isNonRetryable(error: any): boolean {
  // 4xx errors are usually not retryable (except 429 = rate limited)
  const status = error?.response?.status;
  if (status >= 400 && status < 500 && status !== 429) {
    return true;
  }
  return false;
}

/**
 * Normalize error to consistent format.
 */
function normalizeBillingError(error: any): BillingError {
  const status = error?.response?.status;
  const message = error?.message || 'Unknown error';
  const detail = error?.response?.data?.detail || message;

  // Network errors
  if (!error?.response || error.code === 'ECONNREFUSED' || error.code === 'ETIMEDOUT') {
    return {
      type: 'network',
      message,
      userMessage: 'Connection failed. Check your internet and try again.',
      retryable: true,
      originalError: error,
    };
  }

  // Server errors (5xx)
  if (status >= 500) {
    return {
      type: 'server',
      message: detail,
      userMessage: 'Service temporarily unavailable. We\'ll try again in a moment.',
      retryable: true,
      originalError: error,
    };
  }

  // Rate limited
  if (status === 429) {
    return {
      type: 'server',
      message: 'Too many requests',
      userMessage: 'Too many attempts. Wait a moment and try again.',
      retryable: true,
      originalError: error,
    };
  }

  // Validation errors (400)
  if (status === 400) {
    return {
      type: 'validation',
      message: detail,
      userMessage: detail || 'Invalid input. Please check and try again.',
      retryable: false,
      originalError: error,
    };
  }

  // Conflict (409) - e.g., no customer on file
  if (status === 409) {
    return {
      type: 'user_action',
      message: detail,
      userMessage: detail || 'Your account needs updating. Please add a payment method.',
      retryable: false,
      originalError: error,
    };
  }

  // Forbidden (403) - insufficient permissions
  if (status === 403) {
    return {
      type: 'user_action',
      message: detail,
      userMessage: detail || 'You don\'t have permission for this action.',
      retryable: false,
      originalError: error,
    };
  }

  // Card declined, not found, etc.
  if (status === 402 || status === 404) {
    return {
      type: 'user_action',
      message: detail,
      userMessage: detail || 'The payment failed. Please try a different card.',
      retryable: false,
      originalError: error,
    };
  }

  // Default: unknown error
  return {
    type: 'unknown',
    message,
    userMessage: 'Something went wrong. Please try again.',
    retryable: false,
    originalError: error,
  };
}

/**
 * Get cached billing status (for offline support).
 */
async function getCachedBillingStatus() {
  try {
    const cached = await AsyncStorage.getItem('billing_status');
    return cached ? JSON.parse(cached) : null;
  } catch (e) {
    return null;
  }
}

/**
 * Cache billing status locally.
 */
async function cacheBillingStatus(status: any) {
  try {
    await AsyncStorage.setItem('billing_status', JSON.stringify(status));
  } catch (e) {
    // Silently fail if caching fails
  }
}

/**
 * Get billing status with caching and retry logic.
 */
export async function getBillingStatus() {
  try {
    const result = await retryWithBackoff(() => apiClient.getBillingStatus());
    await cacheBillingStatus(result.data);
    return result.data;
  } catch (error) {
    // Fall back to cached version if available
    const cached = await getCachedBillingStatus();
    if (cached) {
      return cached; // Return cached version (may be stale)
    }
    throw normalizeBillingError(error);
  }
}

/**
 * Create setup intent with retry logic.
 */
export async function createSetupIntent() {
  try {
    const result = await retryWithBackoff(() => apiClient.createSetupIntent(), {
      maxRetries: 2, // Fewer retries for user-initiated action
    });
    return result.data;
  } catch (error) {
    throw normalizeBillingError(error);
  }
}

/**
 * Save payment method with validation and retry.
 */
export async function savePaymentMethod(setupIntentId: string) {
  if (!setupIntentId || typeof setupIntentId !== 'string') {
    throw {
      type: 'validation',
      message: 'Invalid setup intent ID',
      userMessage: 'Card setup failed. Please try again.',
      retryable: false,
    };
  }

  try {
    const result = await retryWithBackoff(
      () => apiClient.savePaymentMethod(setupIntentId),
      { maxRetries: 2 }
    );
    return result.data;
  } catch (error) {
    throw normalizeBillingError(error);
  }
}

/**
 * Remove payment method with retry logic.
 */
export async function removePaymentMethod() {
  try {
    const result = await retryWithBackoff(
      () => apiClient.removePaymentMethod(),
      { maxRetries: 2 }
    );
    // Clear cached billing status since it's now stale
    await AsyncStorage.removeItem('billing_status');
    return result.data;
  } catch (error) {
    throw normalizeBillingError(error);
  }
}

/**
 * Validate payment method ID format.
 * Returns true if valid Stripe payment method ID.
 */
export function isValidPaymentMethodId(id: string): boolean {
  // Stripe payment method IDs start with "pm_"
  return typeof id === 'string' && id.startsWith('pm_') && id.length > 3;
}

/**
 * Validate setup intent ID format.
 * Returns true if valid Stripe setup intent ID.
 */
export function isValidSetupIntentId(id: string): boolean {
  // Stripe setup intent IDs start with "seti_"
  return typeof id === 'string' && id.startsWith('seti_') && id.length > 5;
}

/**
 * Validate card brand.
 */
export function isValidCardBrand(brand: string | null): boolean {
  const validBrands = ['visa', 'mastercard', 'amex', 'diners', 'discover', 'jcb'];
  return brand ? validBrands.includes(brand.toLowerCase()) : false;
}

/**
 * Validate last 4 digits.
 */
export function isValidLast4(last4: string | null): boolean {
  return last4 ? /^\d{4}$/.test(last4) : false;
}

/**
 * Format card display string safely.
 */
export function formatCardDisplay(brand: string | null, last4: string | null): string | null {
  if (!brand || !last4) {
    return null;
  }

  const capitalizedBrand = brand.charAt(0).toUpperCase() + brand.slice(1);

  if (!isValidCardBrand(brand) || !isValidLast4(last4)) {
    return null;
  }

  return `${capitalizedBrand} •••• ${last4}`;
}
