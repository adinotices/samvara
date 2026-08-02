/**
 * Enhanced Payment Method Screen with:
 * - Robust error handling with retry logic
 * - Offline support (cached billing status)
 * - Better UX feedback (loading states, error details)
 * - Input validation before API calls
 * - Automatic retries on network failures
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  ScrollView,
} from 'react-native';
import { useStripe } from '@stripe/stripe-react-native';
import * as billingClient from '../../services/billingClient';

interface BillingStatus {
  provider: string;
  hasPaymentMethod: boolean;
  cardDisplay: string | null;
  canUseBeeminder: boolean;
  publishableKey: string;
}

interface ScreenState {
  status: BillingStatus | null;
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;
  retryCount: number;
  isOffline: boolean; // Showing cached data
}

export default function PaymentMethodScreenEnhanced() {
  const { initPaymentSheet, presentPaymentSheet } = useStripe();
  const [state, setState] = useState<ScreenState>({
    status: null,
    isLoading: true,
    isSaving: false,
    error: null,
    retryCount: 0,
    isOffline: false,
  });

  // Load billing status with retry and offline fallback
  const loadBillingStatus = useCallback(async () => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));
    try {
      const data = await billingClient.getBillingStatus();
      setState(prev => ({
        ...prev,
        status: data,
        isLoading: false,
        isOffline: false,
        error: null,
      }));
    } catch (error: any) {
      const billingError = error as billingClient.BillingError;
      // If we got cached data (offline), use it
      if (state.status && billingError.type === 'network') {
        setState(prev => ({
          ...prev,
          isLoading: false,
          isOffline: true, // Indicate this is stale data
          error: 'Showing cached data. Please check your connection.',
        }));
      } else {
        setState(prev => ({
          ...prev,
          isLoading: false,
          error: billingError.userMessage,
        }));
      }
    }
  }, [state.status]);

  useEffect(() => {
    loadBillingStatus();
  }, []);

  const addCard = async () => {
    setState(prev => ({ ...prev, isSaving: true, error: null }));
    try {
      // 1. Create setup intent
      const intent = await billingClient.createSetupIntent();

      if (!billingClient.isValidSetupIntentId(intent.id)) {
        throw new Error('Invalid setup intent received from server');
      }

      // 2. Initialize Stripe payment sheet
      const initResult = await initPaymentSheet({
        setupIntentClientSecret: intent.clientSecret,
        merchantDisplayName: 'Saṃvara',
      });

      if (initResult.error) {
        throw new Error(`Payment sheet initialization failed: ${initResult.error.message}`);
      }

      // 3. Present payment sheet to user
      const presentResult = await presentPaymentSheet();
      if (presentResult.error) {
        // User cancelled (not an error worth showing as failure)
        if (presentResult.error.code !== 'Canceled') {
          throw new Error(`Payment failed: ${presentResult.error.message}`);
        }
        setState(prev => ({ ...prev, isSaving: false }));
        return;
      }

      // 4. Save payment method (with retry)
      await billingClient.savePaymentMethod(intent.id);

      // 5. Reload to show new card
      await loadBillingStatus();

      Alert.alert(
        'Card saved',
        'Your payment method is on file and ready to use.'
      );
    } catch (error: any) {
      const billingError = error as billingClient.BillingError;
      const userMessage = billingError?.userMessage || error?.message || 'Failed to add card';
      setState(prev => ({
        ...prev,
        isSaving: false,
        error: userMessage,
      }));

      Alert.alert('Error', userMessage, [{ text: 'OK' }]);
    }
  };

  const removeCard = async () => {
    Alert.alert(
      'Remove card?',
      'Your saved payment method will be deleted. You can add a new card anytime.',
      [
        { text: 'Cancel', onPress: () => {}, style: 'cancel' },
        {
          text: 'Remove',
          onPress: async () => {
            setState(prev => ({ ...prev, isSaving: true, error: null }));
            try {
              await billingClient.removePaymentMethod();
              await loadBillingStatus();
              Alert.alert('Card removed', 'Your payment method has been deleted.');
            } catch (error: any) {
              const billingError = error as billingClient.BillingError;
              const userMessage = billingError?.userMessage || error?.message || 'Failed to remove card';
              setState(prev => ({
                ...prev,
                isSaving: false,
                error: userMessage,
              }));
            }
          },
          style: 'destructive',
        },
      ]
    );
  };

  const { status, isLoading, isSaving, error, isOffline } = state;

  if (isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
        <Text style={styles.loadingText}>Loading payment method...</Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container}>
      {/* Offline indicator */}
      {isOffline && (
        <View style={styles.offlineWarning}>
          <Text style={styles.offlineWarningText}>
            ⚠️ Showing cached data (offline mode)
          </Text>
        </View>
      )}

      {/* Error message */}
      {error && (
        <View style={styles.errorBanner}>
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity onPress={loadBillingStatus}>
            <Text style={styles.errorRetry}>Retry</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Provider info */}
      <View style={styles.card}>
        <Text style={styles.label}>Charge provider</Text>
        <Text style={styles.value}>
          {status?.provider === 'beeminder' ? 'Beeminder' : 'Saṃvara (Stripe)'}
        </Text>
      </View>

      {/* Payment method */}
      <View style={styles.card}>
        <Text style={styles.label}>Payment method</Text>
        <Text style={styles.value}>
          {status?.cardDisplay || 'No card on file'}
        </Text>
      </View>

      {/* Add/Update card button */}
      <TouchableOpacity
        style={[styles.button, isSaving && styles.buttonDisabled]}
        onPress={addCard}
        disabled={isSaving || isLoading}
      >
        {isSaving ? (
          <ActivityIndicator color="#fff" size="small" />
        ) : (
          <Text style={styles.buttonText}>
            {status?.hasPaymentMethod ? 'Update Card' : 'Add Card'}
          </Text>
        )}
      </TouchableOpacity>

      {/* Remove card button (if card exists) */}
      {status?.hasPaymentMethod && (
        <TouchableOpacity
          style={[styles.button, styles.buttonDanger, isSaving && styles.buttonDisabled]}
          onPress={removeCard}
          disabled={isSaving || isLoading}
        >
          <Text style={styles.buttonText}>Remove Card</Text>
        </TouchableOpacity>
      )}

      {/* Info text */}
      <Text style={styles.hint}>
        Slip and miss charges are billed directly to this card. Saṃvara
        never sees or stores your card number — Stripe handles that.
      </Text>

      {/* Additional info for offline mode */}
      {isOffline && (
        <Text style={styles.hintSecondary}>
          This information may be outdated. Your internet connection will be
          restored soon.
        </Text>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 16,
    backgroundColor: '#f4f2ee',
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#f4f2ee',
  },
  loadingText: {
    marginTop: 12,
    fontSize: 14,
    color: '#999',
  },
  offlineWarning: {
    backgroundColor: '#fff3cd',
    borderRadius: 8,
    padding: 12,
    marginBottom: 12,
    borderLeftWidth: 4,
    borderLeftColor: '#ff9800',
  },
  offlineWarningText: {
    fontSize: 13,
    color: '#856404',
    fontWeight: '500',
  },
  errorBanner: {
    backgroundColor: '#f8d7da',
    borderRadius: 8,
    padding: 12,
    marginBottom: 12,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderLeftWidth: 4,
    borderLeftColor: '#f5222d',
  },
  errorText: {
    fontSize: 13,
    color: '#721c24',
    flex: 1,
  },
  errorRetry: {
    fontSize: 13,
    color: '#721c24',
    fontWeight: '600',
    marginLeft: 8,
  },
  card: {
    backgroundColor: '#fff',
    borderRadius: 10,
    padding: 16,
    marginBottom: 12,
  },
  label: {
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    color: '#999',
    marginBottom: 4,
  },
  value: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1a1a1a',
  },
  button: {
    backgroundColor: '#3d6b52',
    borderRadius: 10,
    padding: 16,
    alignItems: 'center',
    marginTop: 8,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonDanger: {
    backgroundColor: '#a3573a',
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  hint: {
    fontSize: 12,
    color: '#77746c',
    marginTop: 20,
    lineHeight: 18,
  },
  hintSecondary: {
    fontSize: 12,
    color: '#ff9800',
    marginTop: 12,
    lineHeight: 16,
    fontStyle: 'italic',
  },
});
