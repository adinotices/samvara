import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function MetricsScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Metrics</Text>
      <Text style={styles.placeholder}>Metrics dashboard coming soon</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 16,
    backgroundColor: '#f4f2ee',
    justifyContent: 'center',
    alignItems: 'center',
  },
  title: {
    fontSize: 24,
    fontWeight: '600',
    marginBottom: 16,
    color: '#1a1a1a',
  },
  placeholder: {
    fontSize: 14,
    color: '#999',
  },
});
