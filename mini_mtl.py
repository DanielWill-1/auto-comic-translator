import torch
import torch.nn as nn
import torch.optim as optim
import re
import random
import os

# ==========================================
# 1. DATASET PROCESSING (Local File)
# ==========================================
SOS_token = 0  # Start Of Sentence
EOS_token = 1  # End Of Sentence

class Lang:
    def __init__(self, name):
        self.name = name
        self.word2index = {}
        self.word2count = {}
        self.index2word = {0: "SOS", 1: "EOS"}
        self.n_words = 2  

    def addSentence(self, sentence):
        for word in sentence.split(' '):
            self.addWord(word)

    def addWord(self, word):
        if word not in self.word2index:
            self.word2index[word] = self.n_words
            self.word2count[word] = 1
            self.index2word[self.n_words] = word
            self.n_words += 1
        else:
            self.word2count[word] += 1

def normalizeString(s):
    s = s.lower().strip()
    s = re.sub(r"([.!?])", r" \1", s)
    s = re.sub(r"[^a-zA-Z.!?]+", r" ", s)
    return s

def prepareData(file_path='fra.txt'):
    print(f"Reading local dataset from {file_path}...")
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Could not find {file_path}. Make sure it is in the same folder as this script!")

    # Read the local file
    lines = open(file_path, encoding='utf-8').read().strip().split('\n')
    
    # The file has 3 columns (Eng, Fra, Attribution). We only want the first two.
    # We take the first 500 shortest pairs to keep training fast.
    pairs = [[normalizeString(s) for s in l.split('\t')[:2]] for l in lines[:500]]
    
    input_lang = Lang('eng')
    output_lang = Lang('fra')
    
    for pair in pairs:
        input_lang.addSentence(pair[0])
        output_lang.addSentence(pair[1])
        
    return input_lang, output_lang, pairs

# ==========================================
# 2. THE ARCHITECTURE (ENCODER-DECODER)
# ==========================================
class EncoderRNN(nn.Module):
    def __init__(self, input_size, hidden_size):
        super(EncoderRNN, self).__init__()
        self.hidden_size = hidden_size
        self.embedding = nn.Embedding(input_size, hidden_size)
        self.gru = nn.GRU(hidden_size, hidden_size)

    def forward(self, input, hidden):
        embedded = self.embedding(input).view(1, 1, -1)
        output, hidden = self.gru(embedded, hidden)
        return output, hidden

    def initHidden(self, device):
        return torch.zeros(1, 1, self.hidden_size, device=device)

class DecoderRNN(nn.Module):
    def __init__(self, hidden_size, output_size):
        super(DecoderRNN, self).__init__()
        self.hidden_size = hidden_size
        self.embedding = nn.Embedding(output_size, hidden_size)
        self.gru = nn.GRU(hidden_size, hidden_size)
        self.out = nn.Linear(hidden_size, output_size)
        self.softmax = nn.LogSoftmax(dim=1)

    def forward(self, input, hidden):
        output = self.embedding(input).view(1, 1, -1)
        output = torch.relu(output)
        output, hidden = self.gru(output, hidden)
        output = self.softmax(self.out(output[0]))
        return output, hidden

# ==========================================
# 3. TRAINING & UTILS
# ==========================================
def indexesFromSentence(lang, sentence):
    return [lang.word2index[word] for word in sentence.split(' ')]

def tensorFromSentence(lang, sentence, device):
    indexes = indexesFromSentence(lang, sentence)
    indexes.append(EOS_token)
    return torch.tensor(indexes, dtype=torch.long, device=device).view(-1, 1)

def train(input_tensor, target_tensor, encoder, decoder, encoder_optimizer, decoder_optimizer, criterion, device):
    encoder_hidden = encoder.initHidden(device)

    encoder_optimizer.zero_grad()
    decoder_optimizer.zero_grad()

    input_length = input_tensor.size(0)
    target_length = target_tensor.size(0)
    loss = 0

    # Encoder pass
    for ei in range(input_length):
        encoder_output, encoder_hidden = encoder(input_tensor[ei], encoder_hidden)

    # Decoder pass with Teacher Forcing
    decoder_input = torch.tensor([[SOS_token]], device=device)
    decoder_hidden = encoder_hidden

    for di in range(target_length):
        decoder_output, decoder_hidden = decoder(decoder_input, decoder_hidden)
        loss += criterion(decoder_output, target_tensor[di])
        decoder_input = target_tensor[di]  # Teacher forcing

    loss.backward()
    encoder_optimizer.step()
    decoder_optimizer.step()

    return loss.item() / target_length

# ==========================================
# 4. EXECUTION
# ==========================================
if __name__ == "__main__":
    # Your terminal showed CUDA is available, so this will run on your GPU!
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    input_lang, output_lang, pairs = prepareData('fra.txt')
    print(f"Counted words: English={input_lang.n_words}, French={output_lang.n_words}")

    hidden_size = 256
    encoder = EncoderRNN(input_lang.n_words, hidden_size).to(device)
    decoder = DecoderRNN(hidden_size, output_lang.n_words).to(device)

    encoder_optimizer = optim.SGD(encoder.parameters(), lr=0.01)
    decoder_optimizer = optim.SGD(decoder.parameters(), lr=0.01)
    criterion = nn.NLLLoss()

    epochs = 20000
    print(f"\nTraining for {epochs} iterations to overfit the syntax...")
    
    for i in range(1, epochs + 1):
        training_pair = random.choice(pairs)
        input_tensor = tensorFromSentence(input_lang, training_pair[0], device)
        target_tensor = tensorFromSentence(output_lang, training_pair[1], device)

        loss = train(input_tensor, target_tensor, encoder, decoder, encoder_optimizer, decoder_optimizer, criterion, device)
        
        if i % 500 == 0:
            print(f"Iteration {i} | Loss: {loss:.4f}")

    print("\nTraining Complete! Testing learned translations:")
    
    # Inference function
    with torch.no_grad():
        for _ in range(3):
            pair = random.choice(pairs)
            print(f"\n> Original (English): {pair[0]}")
            print(f"= Target (French) : {pair[1]}")
            
            input_tensor = tensorFromSentence(input_lang, pair[0], device)
            encoder_hidden = encoder.initHidden(device)
            
            for ei in range(input_tensor.size(0)):
                encoder_output, encoder_hidden = encoder(input_tensor[ei], encoder_hidden)
                
            decoder_input = torch.tensor([[SOS_token]], device=device)
            decoder_hidden = encoder_hidden
            decoded_words = []
            
            for di in range(10):  # max sentence length
                decoder_output, decoder_hidden = decoder(decoder_input, decoder_hidden)
                topv, topi = decoder_output.data.topk(1)
                if topi.item() == EOS_token:
                    break
                else:
                    decoded_words.append(output_lang.index2word[topi.item()])
                decoder_input = topi.squeeze().detach()
                
            print(f"< Model Output    : {' '.join(decoded_words)}")