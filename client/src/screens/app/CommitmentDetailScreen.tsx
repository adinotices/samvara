import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function CommitmentDetailScreen({ route }: any) {
  const { name } = route.params;

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{name}</Text>
      <Text style={styles.placeholder}>Commitment detail coming soon</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 16,
    backgroundColor: '#f4f2ee',
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
