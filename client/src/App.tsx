import React, { useEffect, useState } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { StripeProvider } from '@stripe/stripe-react-native';
import { useAuthStore } from './store/authStore';
import { AuthStack } from './navigation/AuthStack';
import { AppStack } from './navigation/AppStack';
import { apiClient } from './services/apiClient';

const Stack = createNativeStackNavigator();

export default function App() {
  const token = useAuthStore((state) => state.token);
  const initialized = useAuthStore((state) => state.initialized);
  const init = useAuthStore((state) => state.init);
  // Fetched from GET /v1/billing/status, not hardcoded: Stripe test vs. live
  // mode is decided server-side by which STRIPE_SECRET_KEY the backend is
  // running with, and the client just mirrors that with the matching
  // publishable key.
  const [stripeKey, setStripeKey] = useState<string | null>(null);

  useEffect(() => {
    init();
  }, [init]);

  useEffect(() => {
    if (!token) return;
    apiClient
      .getBillingStatus()
      .then((res) => setStripeKey(res.data.publishableKey || null))
      .catch(() => setStripeKey(null));
  }, [token]);

  if (!initialized) {
    return null; // Show splash screen or loading indicator
  }

  const navigator = (
    <NavigationContainer>
      <Stack.Navigator
        screenOptions={{
          headerShown: false,
          animationEnabled: true,
        }}
      >
        {token ? <AppStack /> : <AuthStack />}
      </Stack.Navigator>
    </NavigationContainer>
  );

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      {stripeKey ? (
        <StripeProvider publishableKey={stripeKey}>{navigator}</StripeProvider>
      ) : (
        navigator
      )}
    </GestureHandlerRootView>
  );
}
