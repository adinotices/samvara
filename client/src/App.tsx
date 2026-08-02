import React, { useEffect } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { useAuthStore } from './store/authStore';
import { AuthStack } from './navigation/AuthStack';
import { AppStack } from './navigation/AppStack';

const Stack = createNativeStackNavigator();

export default function App() {
  const token = useAuthStore((state) => state.token);
  const initialized = useAuthStore((state) => state.initialized);
  const init = useAuthStore((state) => state.init);

  useEffect(() => {
    init();
  }, [init]);

  if (!initialized) {
    return null; // Show splash screen or loading indicator
  }

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
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
    </GestureHandlerRootView>
  );
}
