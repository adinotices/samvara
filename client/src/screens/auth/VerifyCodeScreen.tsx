import React, { useState } from 'react';
import {
  View,
  TextInput,
  TouchableOpacity,
  Text,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { useAuthStore } from '../../store/authStore';

export default function VerifyCodeScreen({ route, navigation }: any) {
  const { email } = route.params;
  const [code, setCode] = useState('');
  const verifyCode = useAuthStore((state) => state.verifyCode);
  const loading = useAuthStore((state) => state.loading);

  const handleVerify = async () => {
    if (!code.trim()) {
      Alert.alert('Error', 'Please enter the code');
      return;
    }

    try {
      await verifyCode(email, code.trim());
    } catch (error: any) {
      Alert.alert('Error', error.message || 'Failed to verify code');
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Verify Code</Text>
      <Text style={styles.subtitle}>
        We sent a code to {email}. Enter it here.
      </Text>

      <TextInput
        style={styles.input}
        placeholder="000000"
        placeholderTextColor="#999"
        value={code}
        onChangeText={setCode}
        editable={!loading}
        keyboardType="number-pad"
        maxLength={6}
      />

      <TouchableOpacity
        style={[styles.button, loading && styles.buttonDisabled]}
        onPress={handleVerify}
        disabled={loading}
      >
        {loading ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>Verify</Text>
        )}
      </TouchableOpacity>

      <TouchableOpacity onPress={() => navigation.goBack()}>
        <Text style={styles.link}>Back to Sign In</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 20,
    justifyContent: 'center',
    backgroundColor: '#f4f2ee',
  },
  title: {
    fontSize: 28,
    fontWeight: '600',
    marginBottom: 12,
    color: '#1a1a1a',
  },
  subtitle: {
    fontSize: 14,
    color: '#666',
    marginBottom: 32,
    lineHeight: 20,
  },
  input: {
    borderWidth: 1,
    borderColor: '#ddd',
    borderRadius: 8,
    padding: 12,
    marginBottom: 16,
    fontSize: 18,
    backgroundColor: '#fff',
    letterSpacing: 4,
    textAlign: 'center',
  },
  button: {
    backgroundColor: '#3d6b52',
    borderRadius: 8,
    padding: 16,
    alignItems: 'center',
    marginBottom: 16,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  link: {
    color: '#3d6b52',
    textAlign: 'center',
    textDecorationLine: 'underline',
  },
});
