import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { useStripe } from '@stripe/stripe-react-native';
import { apiClient } from '../../services/apiClient';

interface BillingStatus {
  provider: string;
  hasPaymentMethod: boolean;
  cardDisplay: string | null;  // e.g. "Visa •••• 4242"
  canUseBeeminder: boolean;
  publishableKey: string;
}

export default function PaymentMethodScreen() {
  const { initPaymentSheet, presentPaymentSheet } = useStripe();
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.getBillingStatus();
      setStatus(res.data);
    } catch (e: any) {
      setError(e?.detail || 'Could not load billing status.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const addCard = async () => {
    setSaving(true);
    setError(null);
    try {
      // 1. Ask the server for a SetupIntent (no charge yet — just a card save).
      const intentRes = await apiClient.createSetupIntent();
      const { clientSecret, id: setupIntentId } = intentRes.data;

      // 2. Let Stripe's native sheet collect the card.
      const initResult = await initPaymentSheet({
        setupIntentClientSecret: clientSecret,
        merchantDisplayName: 'Saṃvara',
      });
      if (initResult.error) {
        throw new Error(initResult.error.message);
      }
      const presentResult = await presentPaymentSheet();
      if (presentResult.error) {
        // User cancellation isn't an error worth surfacing as a failure banner.
        if (presentResult.error.code !== 'Canceled') {
          throw new Error(presentResult.error.message);
        }
        return;
      }

      // 3. The SetupIntent is confirmed client-side, but the raw
      // payment_method id isn't reliably exposed by the SDK across versions
      // — hand the SetupIntent id to the server and let it look the id up
      // directly against Stripe (see stripe_billing.get_setup_intent_payment_method).
      await apiClient.savePaymentMethod(setupIntentId);

      await load();
      Alert.alert('Card saved', 'Your payment method is on file.');
    } catch (e: any) {
      setError(e?.message || e?.detail || 'Could not save your card.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.card}>
        <Text style={styles.label}>Charge provider</Text>
        <Text style={styles.value}>
          {status?.provider === 'beeminder' ? 'Beeminder' : 'Saṃvara (Stripe)'}
        </Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.label}>Payment method</Text>
        <Text style={styles.value}>
          {status?.cardDisplay || 'No card on file'}
        </Text>
      </View>

      {error && <Text style={styles.error}>{error}</Text>}

      <TouchableOpacity
        style={styles.button}
        onPress={addCard}
        disabled={saving}
      >
        {saving ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>
            {status?.hasPaymentMethod ? 'Update Card' : 'Add Card'}
          </Text>
        )}
      </TouchableOpacity>

      <Text style={styles.hint}>
        Slip and miss charges are billed directly to this card. Saṃvara
        never sees or stores your card number — Stripe handles that.
      </Text>
    </View>
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
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  error: {
    color: '#a3573a',
    marginBottom: 12,
  },
  hint: {
    fontSize: 12,
    color: '#77746c',
    marginTop: 16,
    lineHeight: 18,
  },
});
