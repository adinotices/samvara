import { create } from 'zustand';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { apiClient } from '../services/apiClient';

interface AuthState {
  token: string | null;
  email: string | null;
  initialized: boolean;
  loading: boolean;
  error: string | null;

  // Actions
  init: () => Promise<void>;
  signIn: (email: string) => Promise<void>;
  verifyCode: (email: string, code: string) => Promise<void>;
  signOut: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  email: null,
  initialized: false,
  loading: false,
  error: null,

  init: async () => {
    try {
      const storedToken = await AsyncStorage.getItem('apiToken');
      const storedEmail = await AsyncStorage.getItem('email');

      if (storedToken && storedEmail) {
        set({ token: storedToken, email: storedEmail });
        apiClient.setToken(storedToken);
      }
    } catch (e) {
      console.warn('Failed to restore auth state:', e);
    } finally {
      set({ initialized: true });
    }
  },

  signIn: async (email: string) => {
    set({ loading: true, error: null });
    try {
      await apiClient.sendCode(email);
      set({ email, loading: false });
    } catch (error: any) {
      set({
        error: error?.message || 'Failed to sign in',
        loading: false
      });
      throw error;
    }
  },

  verifyCode: async (email: string, code: string) => {
    set({ loading: true, error: null });
    try {
      const response = await apiClient.verifyCode(email, code);
      const token = response.token;

      await AsyncStorage.multiSet([
        ['apiToken', token],
        ['email', email],
      ]);

      apiClient.setToken(token);
      set({ token, email, loading: false });
    } catch (error: any) {
      set({
        error: error?.message || 'Failed to verify code',
        loading: false
      });
      throw error;
    }
  },

  signOut: async () => {
    set({ loading: true });
    try {
      // Call API to revoke session
      await apiClient.signOut();
    } catch (error) {
      console.warn('Failed to revoke session on server:', error);
    }

    // Clear local state regardless
    await AsyncStorage.multiRemove(['apiToken', 'email']);
    apiClient.setToken(null);
    set({ token: null, email: null, loading: false });
  },

  clearError: () => set({ error: null }),
}));
