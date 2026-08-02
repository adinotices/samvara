import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export default function SessionsScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.placeholder}>Active sessions coming soon</Text>
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
  placeholder: {
    fontSize: 14,
    color: '#999',
  },
});
