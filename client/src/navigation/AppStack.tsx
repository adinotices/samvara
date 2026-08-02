import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';
import CommitmentsScreen from '../screens/app/CommitmentsScreen';
import CommitmentDetailScreen from '../screens/app/CommitmentDetailScreen';
import MetricsScreen from '../screens/app/MetricsScreen';
import SettingsScreen from '../screens/app/SettingsScreen';
import NotificationsScreen from '../screens/app/NotificationsScreen';
import SessionsScreen from '../screens/app/SessionsScreen';

const Stack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();

function CommitmentsStack() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: true,
        headerBackTitleVisible: false,
      }}
    >
      <Stack.Screen
        name="CommitmentsList"
        component={CommitmentsScreen}
        options={{ title: 'Commitments' }}
      />
      <Stack.Screen
        name="CommitmentDetail"
        component={CommitmentDetailScreen}
        options={({ route }: any) => ({
          title: route.params?.name || 'Commitment',
        })}
      />
    </Stack.Navigator>
  );
}

function MetricsStack() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: true,
        headerBackTitleVisible: false,
      }}
    >
      <Stack.Screen
        name="MetricsList"
        component={MetricsScreen}
        options={{ title: 'Metrics' }}
      />
    </Stack.Navigator>
  );
}

function SettingsStack() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: true,
        headerBackTitleVisible: false,
      }}
    >
      <Stack.Screen
        name="SettingsMain"
        component={SettingsScreen}
        options={{ title: 'Settings' }}
      />
      <Stack.Screen
        name="Notifications"
        component={NotificationsScreen}
        options={{ title: 'Notifications' }}
      />
      <Stack.Screen
        name="Sessions"
        component={SessionsScreen}
        options={{ title: 'Active Sessions' }}
      />
    </Stack.Navigator>
  );
}

export function AppStack() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarIcon: ({ focused, color, size }) => {
          let iconName: keyof typeof Ionicons.glyphMap = 'checkmark-circle';

          if (route.name === 'CommitmentsTab') {
            iconName = focused ? 'checkmark-circle' : 'checkmark-circle-outline';
          } else if (route.name === 'MetricsTab') {
            iconName = focused ? 'bar-chart' : 'bar-chart-outline';
          } else if (route.name === 'SettingsTab') {
            iconName = focused ? 'settings' : 'settings-outline';
          }

          return <Ionicons name={iconName} size={size} color={color} />;
        },
        tabBarActiveTintColor: '#3d6b52',
        tabBarInactiveTintColor: '#cccccc',
      })}
    >
      <Tab.Screen
        name="CommitmentsTab"
        component={CommitmentsStack}
        options={{ title: 'Commitments' }}
      />
      <Tab.Screen
        name="MetricsTab"
        component={MetricsStack}
        options={{ title: 'Metrics' }}
      />
      <Tab.Screen
        name="SettingsTab"
        component={SettingsStack}
        options={{ title: 'Settings' }}
      />
    </Tab.Navigator>
  );
}
