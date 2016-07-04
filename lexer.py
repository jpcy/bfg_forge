# BFG Forge
# Based on Level Buddy by Matt Lucas
# https://matt-lucas.itch.io/level-buddy

#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	 See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.	 If not, see <http://www.gnu.org/licenses/>.

class Lexer:
	valid_token_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_/\\-.&:"
	valid_single_tokens = "{}[]()+-*/%!=<>,"

	def __init__(self, filename):
		self.line, self.pos = 1, 0
		with open(filename) as file:
			self.data = file.read()
			
	def eof(self):
		return self.pos >= len(self.data)
		
	def expect_token(self, token):
		t = self.parse_token()
		if not token == t:
			raise Exception("expected token \"%s\", got \"%s\" on line %d" % (token, t, self.line))
		
	def parse_token(self):
		self.skip_whitespace()
		if self.eof():
			return None
		start = self.pos
		while True:
			if self.eof():
				break
			c = self.data[self.pos]
			nc = self.data[self.pos + 1] if self.pos + 1 < len(self.data) else None
			if c == "\"":
				if not start == self.pos:
					raise Exception("quote in middle of token")
				self.pos += 1
				while True:
					if self.eof():
						raise Exception("eof in quoted token")
					c = self.data[self.pos]
					self.pos += 1
					if c == "\"":
						return self.data[start + 1:self.pos - 1]
			elif (c == "/" and nc == "/") or (c == "/" and nc == "*"):
				break
			elif not c in self.valid_token_chars:
				if c in self.valid_single_tokens:
					if self.pos == start:
						# single character token
						self.pos += 1
				break
			self.pos += 1
		end = self.pos
		return self.data[start:end]
		
	def skip_bracket_delimiter_section(self, opening, closing, already_open = False):
		if not already_open:
			self.expect_token(opening)
		num_required_closing = 1
		while True:
			token = self.parse_token()
			if token == None:
				break
			elif token == opening:
				num_required_closing += 1
			elif token == closing:
				num_required_closing -= 1
				if num_required_closing == 0:
					break
		
	def skip_whitespace(self):
		while True:
			if self.eof():
				break
			c = self.data[self.pos]
			nc = self.data[self.pos + 1] if self.pos + 1 < len(self.data) else None
			if c == "\n":
				self.line += 1
				self.pos += 1
			elif ord(c) <= ord(" "):
				self.pos += 1
			elif c == "/" and nc == "/":
				while True:
					if self.eof() or self.data[self.pos] == "\n":
						break
					self.pos += 1
			elif c == "/" and nc == "*":
				while True:
					if self.eof():
						break
					c = self.data[self.pos]
					nc = self.data[self.pos + 1] if self.pos + 1 < len(self.data) else None
					if c == "*" and nc == "/":
						self.pos += 2
						break
					self.pos += 1
			else:
				break
				
if __name__ == "__main__":
	'''
	lex = Lexer(r"")
	while True:
		last_pos = lex.pos
		token = lex.parse_token()
		if token == None:
			break
		if lex.pos == last_pos:
			raise Exception("hang detected")
			break
		print(token)
	'''
