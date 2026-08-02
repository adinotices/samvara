import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import SignInScreen from '../screens/auth/SignInScreen';
import VerifyCodeScreen from '../screens/auth/VerifyCodeScreen';
import AccessRequestScreen from '../screens/auth/AccessRequestScreen';

const Stack = createNativeStackNavigator();

export function AuthStack() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        animationEnabled: true,
      }}
    >
      <Stack.Screen
        name="SignIn"
        component={SignInScreen}
        options={{ title: 'Sign In' }}
      />
      <Stack.Screen
        name="VerifyCode"
        component={VerifyCodeScreen}
        options={{ title: 'Verify Code' }}
      />
      <Stack.Screen
        name="AccessRequest"
        component={AccessRequestScreen}
        options={{ title: 'Request Access' }}
      />
    </Stack.Navigator>
  );
}
